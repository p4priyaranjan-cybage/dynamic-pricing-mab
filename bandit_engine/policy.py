"""Vowpal Wabbit contextual bandit wrapper + ensemble-blend architecture.

Implements (see docs/ARCHITECTURE.md for the full design writeup):

  - `BackboneModel`: one per (cluster_id, tenant_id). Shared/pooled learning.
    SLOW-updating only - it is retrained via explicit batch calls
    (bandit_engine/training/train.py), never from a single live online
    event, so one property's feedback can never instantly leak into
    another property's decisions through the backbone.
    Internally maintains a small manual online-bagging ensemble (N
    independent CB_ADF workspaces) purely so the "model agreement"
    confidence component can inspect each member's individual prediction -
    VW's built-in --bag explore mode does not expose per-member predictions
    through the simple predict() API, so this reimplements the same idea
    (Poisson(1) online-bagging resampling) explicitly.

  - `PropertyModel`: one per property_id. FAST-updating, physically
    separate VW workspace/model file - a hard isolation guarantee that one
    property's feedback can never alter another property's weights, since
    they are different objects/files entirely.

  - `EnsemblePolicy`: combines the two via empirical-Bayes credibility
    weighting w = n_property / (n_property + k). w is itself reused as the
    "sample size" component of the confidence score. Blend weight k (and
    therefore how quickly a property "graduates" to trusting its own data)
    is a per-tenant config knob (config/tenants/*.yaml `ensemble.blend_smoothing_k`).
    Setting k -> 0 effectively makes w -> 1 for any property with at least
    one observation, i.e. full independence - the opt-out path discussed in
    the design for tenants who don't want pooling at all.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from vowpalwabbit import pyvw

from model_registry.versioning import create_version_dir, get_current_version_dir, prune_old_versions

MODEL_DIR = Path(__file__).resolve().parent.parent / "model_registry" / "artifacts"
N_BAG_MEMBERS = 5
_VW_ARGS = "--cb_explore_adf -q ca --quiet --learning_rate 0.5 --random_seed {seed}"


# --------------------------------------------------------------------------- #
# VW example construction helpers
# --------------------------------------------------------------------------- #

def _context_line(context: dict) -> str:
    """Render a context dict into a VW `shared |c ...` feature line.

    property_id/cluster_id/tenant_id are excluded from the raw feature text
    because model ROUTING already encodes them (which BackboneModel /
    PropertyModel instance is used) - including them as literal string
    features as well would be redundant and risks VW-reserved characters.
    """
    parts = []
    for key, value in context.items():
        if key in ("property_id", "cluster_id", "tenant_id"):
            continue
        if isinstance(value, bool):
            if value:
                parts.append(key)
        elif isinstance(value, (int, float)):
            parts.append(f"{key}:{value}")
        else:
            safe = str(value).replace(" ", "_").replace(":", "_").replace("|", "_")
            parts.append(f"{key}_{safe}")
    return "shared |c " + " ".join(parts)


def _arm_body(arm: dict) -> str:
    label = str(arm["label"]).replace(" ", "_")
    return f"arm_idx_{arm['index']} arm_label_{label}"


def _arm_line(arm: dict, label_prefix: Optional[str] = None) -> str:
    body = _arm_body(arm)
    if label_prefix:
        return f"{label_prefix} |a {body}"
    return f"|a {body}"


def _poisson1(rng: random.Random) -> int:
    """Sample from Poisson(1) - used for online-bagging resample weights."""
    l = math.exp(-1.0)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1


@dataclass
class ScoredArm:
    index: int
    label: str
    offset_pct: float
    probability: float


# --------------------------------------------------------------------------- #
# Backbone (cluster x tenant) - shared, slow-updating
# --------------------------------------------------------------------------- #

class BackboneModel:
    def __init__(self, cluster_id: str, tenant_id: str, n_members: int = N_BAG_MEMBERS):
        self.cluster_id = cluster_id
        self.tenant_id = tenant_id
        self.n_members = n_members
        self._rng = random.Random(f"{tenant_id}:{cluster_id}")
        self.members = [
            pyvw.Workspace(_VW_ARGS.format(seed=i)) for i in range(n_members)
        ]

    def predict_bag(self, context: dict, arms: list[dict]) -> list[list[float]]:
        """Return one probability list per bag member, each aligned to `arms`."""
        shared_line = _context_line(context)
        action_lines = [_arm_line(a) for a in arms]
        out = []
        for vw in self.members:
            ex = vw.parse([shared_line, *action_lines], labelType=pyvw.LabelType.CONTEXTUAL_BANDIT)
            out.append(list(vw.predict(ex)))
            vw.finish_example(ex)
        return out

    def predict(self, context: dict, arms: list[dict]) -> list[float]:
        """Average PMF across bag members - the backbone's blended prediction."""
        bag = self.predict_bag(context, arms)
        n = len(arms)
        avg = [0.0] * n
        for probs in bag:
            for i in range(n):
                avg[i] += probs[i] / len(bag)
        return avg

    def learn_batch(self, examples: list[dict]) -> None:
        """Batch retrain from reconciled (context, arms, chosen_pos, propensity,
        reward) tuples. This is the ONLY way the backbone updates.

        Training strategy: multiple passes over the data to strengthen the
        context→arm signal. VW's online learning needs repeated exposure to
        converge, especially with diverse contexts."""
        N_PASSES = 3  # repeat training data to reinforce patterns
        for _pass in range(N_PASSES):
            for vw in self.members:
                for rec in examples:
                    weight = _poisson1(self._rng)
                    if weight == 0:
                        continue
                    shared_line = _context_line(rec["context"])
                    arms = rec["arms"]
                    chosen_pos = rec["chosen_pos"]
                    cost = -rec["reward"]
                    lines = []
                    for pos, arm in enumerate(arms):
                        if pos == chosen_pos:
                            lines.append(_arm_line(arm, f"{pos}:{cost}:{rec['propensity']}"))
                        else:
                            lines.append(_arm_line(arm))
                    ex = vw.parse([shared_line, *lines], labelType=pyvw.LabelType.CONTEXTUAL_BANDIT)
                    for _ in range(weight):
                        vw.learn(ex)
                    vw.finish_example(ex)

    def save(self) -> Path:
        base_dir = MODEL_DIR / "backbone" / f"{self.tenant_id}__{self.cluster_id}"
        out_dir = create_version_dir(base_dir)
        for i, vw in enumerate(self.members):
            vw.save(str(out_dir / f"member_{i}.vw"))
        prune_old_versions(base_dir)
        return out_dir

    @classmethod
    def load_or_create(cls, cluster_id: str, tenant_id: str) -> "BackboneModel":
        model = cls(cluster_id, tenant_id)
        base_dir = MODEL_DIR / "backbone" / f"{tenant_id}__{cluster_id}"
        in_dir = get_current_version_dir(base_dir)
        if in_dir is not None:
            for i in range(model.n_members):
                f = in_dir / f"member_{i}.vw"
                if f.exists():
                    model.members[i] = pyvw.Workspace(_VW_ARGS.format(seed=i) + f" -i {f}")
        return model


# --------------------------------------------------------------------------- #
# Property model - isolated, fast-updating
# --------------------------------------------------------------------------- #

class PropertyModel:
    def __init__(self, property_id: str):
        self.property_id = property_id
        self.vw = pyvw.Workspace(_VW_ARGS.format(seed=0))
        self.n_observations = 0

    def predict(self, context: dict, arms: list[dict]) -> list[float]:
        shared_line = _context_line(context)
        action_lines = [_arm_line(a) for a in arms]
        ex = self.vw.parse([shared_line, *action_lines], labelType=pyvw.LabelType.CONTEXTUAL_BANDIT)
        probs = list(self.vw.predict(ex))
        self.vw.finish_example(ex)
        return probs

    def learn(
        self, context: dict, arms: list[dict], chosen_pos: int, propensity: float, reward: float,
        count_as_observation: bool = True,
    ) -> None:
        """Fast, online, isolated update - ONLY this property's own data ever
        touches these weights (hard guarantee: physically separate object).

        `count_as_observation=False` is used by bootstrap pretraining
        (bandit_engine/training/train.py) - it still updates these VW
        weights (so the property isn't a blank slate), but deliberately
        does NOT increment `n_observations`, which is what the ensemble's
        credibility weight `w = n_observations / (n_observations + k)` is
        based on. Counting synthetic, reward-model-imputed bootstrap
        examples as "earned trust" observations would let a freshly
        bootstrapped property jump to ~99% self-trust (and ~1% backbone
        influence) before a single REAL interaction ever happened,
        defeating the entire point of the credibility-weighted blend - see
        docs/ARCHITECTURE.md "Reliability plan" for the diagnosis."""
        shared_line = _context_line(context)
        cost = -reward
        lines = []
        for pos, arm in enumerate(arms):
            if pos == chosen_pos:
                lines.append(_arm_line(arm, f"{pos}:{cost}:{propensity}"))
            else:
                lines.append(_arm_line(arm))
        ex = self.vw.parse([shared_line, *lines], labelType=pyvw.LabelType.CONTEXTUAL_BANDIT)
        self.vw.learn(ex)
        self.vw.finish_example(ex)
        if count_as_observation:
            self.n_observations += 1

    def save(self) -> Path:
        base_dir = MODEL_DIR / "property" / self.property_id
        out_dir = create_version_dir(base_dir)
        self.vw.save(str(out_dir / "model.vw"))
        (out_dir / "n_observations.txt").write_text(str(self.n_observations))
        prune_old_versions(base_dir)
        return out_dir

    @classmethod
    def load_or_create(cls, property_id: str) -> "PropertyModel":
        model = cls(property_id)
        base_dir = MODEL_DIR / "property" / property_id
        in_dir = get_current_version_dir(base_dir)
        if in_dir is not None:
            f = in_dir / "model.vw"
            if f.exists():
                model.vw = pyvw.Workspace(_VW_ARGS.format(seed=0) + f" -i {f}")
                n_file = in_dir / "n_observations.txt"
                if n_file.exists():
                    model.n_observations = int(n_file.read_text().strip() or 0)
        return model


# --------------------------------------------------------------------------- #
# Ensemble policy (property + backbone, credibility-weighted) + confidence
# --------------------------------------------------------------------------- #

@dataclass
class DecisionResult:
    chosen: ScoredArm
    propensity: float
    all_arms: list[ScoredArm]
    confidence: float
    confidence_label: str
    confidence_breakdown: dict
    blend_weight: float


class EnsemblePolicy:
    def __init__(
        self,
        property_model: PropertyModel,
        backbone_model: BackboneModel,
        blend_smoothing_k: float,
        confidence_weights: dict,
    ):
        self.property_model = property_model
        self.backbone_model = backbone_model
        self.k = blend_smoothing_k
        self.cw = confidence_weights

    def _credibility_weight(self) -> float:
        n = self.property_model.n_observations
        return n / (n + self.k) if (n + self.k) > 0 else 0.0

    def decide(self, context: dict, arms: list[dict], explore: bool = True, seed: Optional[int] = None) -> DecisionResult:
        w = self._credibility_weight()
        property_probs = self.property_model.predict(context, arms)
        backbone_bag = self.backbone_model.predict_bag(context, arms)
        backbone_probs = [sum(p[i] for p in backbone_bag) / len(backbone_bag) for i in range(len(arms))]

        blended = [w * property_probs[i] + (1 - w) * backbone_probs[i] for i in range(len(arms))]
        total = sum(blended) or 1.0
        blended = [p / total for p in blended]

        rng = random.Random(seed)
        if explore:
            r, cum, chosen_pos = rng.random(), 0.0, len(blended) - 1
            for i, p in enumerate(blended):
                cum += p
                if r <= cum:
                    chosen_pos = i
                    break
        else:
            chosen_pos = max(range(len(blended)), key=lambda i: blended[i])

        propensity = blended[chosen_pos]
        scored_arms = [
            ScoredArm(index=arms[i]["index"], label=arms[i]["label"], offset_pct=arms[i]["offset_pct"], probability=blended[i])
            for i in range(len(arms))
        ]
        chosen = scored_arms[chosen_pos]

        # --- confidence score (see docs/ARCHITECTURE.md "Confidence score") ---
        c_sample = w
        bag_probs_for_chosen = [p[chosen_pos] for p in backbone_bag]
        mean_bag = sum(bag_probs_for_chosen) / len(bag_probs_for_chosen)
        var_bag = sum((p - mean_bag) ** 2 for p in bag_probs_for_chosen) / len(bag_probs_for_chosen)
        std_bag = math.sqrt(var_bag)
        c_agreement = 1.0 - min(1.0, (std_bag / mean_bag) if mean_bag > 1e-9 else 1.0)

        sorted_probs = sorted(blended, reverse=True)
        second_best = sorted_probs[1] if len(sorted_probs) > 1 else 0.0
        c_margin = max(0.0, propensity - second_best)

        composite = (
            self.cw.get("w_sample", 0.4) * c_sample
            + self.cw.get("w_agreement", 0.35) * c_agreement
            + self.cw.get("w_margin", 0.25) * c_margin
        )
        composite = max(0.0, min(1.0, composite))
        label = "High" if composite > 0.7 else ("Medium" if composite >= 0.4 else "Low")

        return DecisionResult(
            chosen=chosen,
            propensity=propensity,
            all_arms=scored_arms,
            confidence=round(composite, 4),
            confidence_label=label,
            confidence_breakdown={
                "sample": round(c_sample, 4),
                "agreement": round(c_agreement, 4),
                "margin": round(c_margin, 4),
            },
            blend_weight=round(w, 4),
        )

    def record_feedback(self, context: dict, arms: list[dict], chosen_pos: int, propensity: float, reward: float) -> None:
        """Fast loop: updates ONLY the property's own model, immediately."""
        self.property_model.learn(context, arms, chosen_pos, propensity, reward)
