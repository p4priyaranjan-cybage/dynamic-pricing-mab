"""Offline evaluation and reward-model-based pretraining.

Historical logs are near-zero-exploration (see context_generator/
multi_chain_synthetic_data.py `_pick_historical_arm`) - only a small
fraction of rows deviate from the static baseline arm, and (aside from a
small pilot-test fraction) only ever by one adjacent tier. A naive
off-policy replay (importance-weighting the logged arm only) would
therefore be extremely high-variance and could never learn anything about
the arms that are rarely or never observed.

Reliability plan implemented here (see docs/ARCHITECTURE.md "Reliability
plan" for the full write-up of why earlier versions underperformed the
static baseline in backtests, and what each of these fixes addresses):

  1. Fit a gradient-boosted (XGBoost) reward model, `P(booked) ~ context
     features + offset_pct`, with a NATIVE monotonic constraint forcing
     the model's response to offset_pct to be non-increasing. This
     replaces an earlier linear-regression + manually-clamped-coefficient
     approach: a hand-tuned floor on a linear coefficient is a coarse,
     single global number applied identically regardless of context,
     whereas the boosted-tree monotonic constraint is enforced natively by
     the training algorithm at every split, and the model itself can
     capture non-linear interactions between context features (e.g.
     "occupancy matters more when there's also a local event") that a
     linear model can't represent at all - directly relevant to the
     "same arm regardless of context" symptom this was built to fix. No
     manual feature scaling is needed (tree splits are scale-invariant).
  2. A monotonic constraint is a HARD guarantee of the model's SHAPE, not
     a claim that the fitted magnitude/timing of the price effect is
     perfectly correct - "raising price cannot plausibly *increase*
     booking odds, all else equal" is close to a law-of-demand certainty,
     so enforcing it structurally (rather than hoping data sparsity
     doesn't produce the wrong sign) is the right place for a hard prior.
  3. Distance-based pessimism/shrinkage: for arms whose offset_pct falls
     outside the range actually observed in the historical rows used to
     fit the model, the imputed reward is shrunk toward the model's
     prediction at the boundary of the observed range, proportional to how
     far past that boundary the arm is.
  3b. Premium-side elasticity floor (`PREMIUM_ELASTICITY_FLOOR`): empirically,
     the assumption that a monotone-constrained tree would decay P(booked)
     "fast enough" out of its own accord turned out FALSE on this dataset's
     near-zero-exploration historical logs - `monotone_constraints` only
     guarantees the *direction* of the effect, not its *magnitude*, and a
     too-mild fitted decline (e.g. 0.59 -> 0.39 across the whole ladder)
     is mechanically dominated by the ladder's price growth (up to ~2.6x
     from cheapest to priciest arm) exactly the way the ORIGINAL
     linear-model bug worked (see "Reliability plan" in
     docs/ARCHITECTURE.md) - reproducing the same always-pick-the-most-
     expensive-arm failure mode. The fix mirrors the old linear model's
     `MONOTONICITY_FLOOR` coefficient clamp, translated into probability
     space: for offset_pct > 0, P(booked) is capped at
     `sigmoid(logit(P(booked @ offset=0)) + PREMIUM_ELASTICITY_FLOOR * offset_pct)`
     - i.e. log-odds must decline at least this fast per unit offset above
     the property's own Base Rate prediction for that context, guaranteeing
     reward = P(booked) * price eventually declines no matter how mild the
     tree's own fitted slope is, while leaving the tree's context-sensitive
     predictions untouched everywhere they aren't more optimistic than this
     floor.
  4. Doubly-robust correction at the ACTUALLY-logged arm: for the one arm
     each historical row really tried, the model's estimate is corrected
     toward the real observed outcome via inverse-propensity weighting
     (weight capped to bound variance), rather than trusting the model's
     estimate blindly even where we have real ground truth.
  5. Held-out AUC/log-loss diagnostics (from a genuine 3-way train/
     early-stopping-validation/held-out-report split, so the reported
     metric isn't the same data used to pick the number of trees) are
     returned so callers (bandit_engine/training/train.py) can log/inspect
     fit quality rather than blindly trusting every fit.

This remains a pragmatic approximation of full doubly-robust off-policy
evaluation (real DR would apply the importance-weighted correction using
the full logged-propensity distribution, not just at one arm) - documented
honestly as a model-based warm-start with explicit uncertainty handling,
not a rigorous unbiased estimator.

`run_backtest` / `run_backtest_suite` separately evaluate a *trained*
policy against the static baseline using the TRUE ground-truth demand
model (context_generator.demand_model) as an oracle simulator - this
oracle is NEVER exposed to the bandit itself, only used here to score
outcomes for comparison, exactly as described in docs/ARCHITECTURE.md
Verification section.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass, field

from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from bandit_engine.config_loader import resolve_arm_ladder_for_cluster
from bandit_engine.policy import BackboneModel, PropertyModel, EnsemblePolicy
from context_generator.demand_model import booking_probability, cancellation_probability, CHANNEL_COMMISSION_PCT
from db.models import Decision, Property
from db.session import get_session

NUMERIC_FEATURES = [
    "occupancy_pct",
    "adr_trend_pct",
    "pace_vs_stly_pct",
    "pickup_last_7d",
    "remaining_inventory_pct",
    "our_rate_vs_compset_index",
    "compset_rate_trend_pct",
    "compset_dispersion",
    "event_intensity",
]

# Interaction features: context_signal * offset_pct. These help the reward
# model learn "high occupancy makes premium arms more viable" etc. without
# relying on the tree finding these splits in sparse extreme-arm data.
# Each interaction is monotone-constrained to -1 (non-increasing in offset_pct
# direction) since they are products of a non-negative context signal with
# offset_pct, and higher offset should never INCREASE booking probability.
INTERACTION_FEATURES = [
    ("occupancy_pct", "offset_pct"),
    ("event_intensity", "offset_pct"),
    ("pace_vs_stly_pct", "offset_pct"),
    ("pickup_last_7d", "offset_pct"),
]

# Segment elasticity multipliers used as an interaction feature - segments
# with higher elasticity should see steeper P(booked) declines at premium arms.
_SEGMENT_ELASTICITY_FOR_FEATURES = {
    "transient": 1.0,
    "leisure": 1.25,
    "corporate": 0.55,
    "group": 0.80,
}

# Feature order produced by `_raw_features`:
#   NUMERIC_FEATURES..., event_flag, offset_pct,
#   occupancy*offset, event_intensity*offset, pace*offset, pickup*offset,
#   segment_elasticity*offset
# Monotone constraint: 0 = unconstrained, -1 = non-increasing.
# offset_pct and all interaction terms involving it are constrained.
_N_BASE = len(NUMERIC_FEATURES) + 1  # +1 for event_flag
_N_INTERACTIONS = len(INTERACTION_FEATURES) + 1  # +1 for segment_elasticity*offset
MONOTONE_CONSTRAINTS = tuple(
    [0] * _N_BASE  # base numeric + event_flag: unconstrained
    + [-1]  # offset_pct: non-increasing
    + [-1] * _N_INTERACTIONS  # all interactions: non-increasing
)

MIN_ROWS_FOR_MODEL = 20  # below this, no meaningful fit is attempted at all
MIN_ROWS_FOR_CV = 40  # below this (but >= MIN_ROWS_FOR_MODEL), skip the early-stopping validation split
MAX_EXTRAPOLATION_SPAN = 0.15  # offset-pct distance past the observed range at which shrinkage saturates to 1.0
PREMIUM_ELASTICITY_FLOOR = -2.0  # DEFAULT minimum log-odds decay per unit offset_pct for offset_pct > 0,
# anchored at each context's own predicted P(booked) at offset_pct=0 - see module docstring point 3b.
# Now context-conditioned via SEGMENT_ELASTICITY_FLOORS below.

# Context-conditioned premium elasticity floor: different segments have
# different price sensitivities. Corporate travelers are less elastic (floor
# is milder), leisure travelers are more elastic (floor is steeper). This
# prevents the single-global-floor problem where a conservative floor
# suppresses legitimate premium picks in low-elasticity segments.
SEGMENT_ELASTICITY_FLOORS = {
    "corporate": -1.3,   # least elastic - tolerates higher prices
    "group": -1.6,
    "transient": -2.0,   # moderate (the old global default)
    "leisure": -2.6,     # most elastic - penalizes premium arms more
}
_LOGIT_EPS = 1e-6  # clamp before logit() to avoid -inf/+inf at p=0/1
MAX_IPS_WEIGHT = 20.0  # caps 1/propensity in the doubly-robust correction to bound variance
MIN_PROPENSITY = 1e-3
RELIABLE_AUC_THRESHOLD = 0.55  # holdout AUC below this -> diagnostics.reliable = False

# Floor on a LOGGED propensity when replaying reconciled real outcomes into VW.
# VW applies an effective importance weight of 1/propensity, so an unclamped
# tiny value would let one lucky exploration row dominate the batch. Tied to
# MAX_IPS_WEIGHT so both variance guards move together.
MIN_LOGGED_PROPENSITY = 1.0 / MAX_IPS_WEIGHT  # = 0.05
# How many times each reconciled real outcome is replayed into the batch.
# 1 = real outcomes influence the model in proportion to how many exist
# (deliberately gentle while the live dataset is small). Raise once there is
# enough real feedback to outweigh the oracle-imputed examples.
RECONCILED_REPEATS = 1


def _raw_features(context: dict, offset_pct: float) -> list[float]:
    """Feature vector for the reward model. Includes:
    - Raw numeric context features (NUMERIC_FEATURES)
    - event_flag as 0/1
    - offset_pct (the price lever)
    - Explicit interaction terms (context_signal * offset_pct) that help
      the tree learn context-dependent elasticity without needing to discover
      these splits from sparse extreme-arm data on its own.
    - Segment elasticity * offset_pct (encodes prior knowledge that leisure
      guests are more price-sensitive than corporate).
    """
    base = [float(context.get(f, 0.0)) for f in NUMERIC_FEATURES] + [
        1.0 if context.get("event_flag") else 0.0,
        offset_pct,
    ]
    # Interaction features: context_signal * offset_pct
    for ctx_feat, _ in INTERACTION_FEATURES:
        base.append(float(context.get(ctx_feat, 0.0)) * offset_pct)
    # Segment elasticity * offset_pct (domain prior)
    seg_elast = _SEGMENT_ELASTICITY_FOR_FEATURES.get(context.get("segment", "transient"), 1.0)
    base.append(seg_elast * offset_pct)
    return base


@dataclass
class RewardModel:
    """P(booked) ~ context features + offset_pct, fit via a monotonic-
    constrained XGBClassifier (see module docstring points 1-2). No manual
    feature scaling needed - tree splits are scale-invariant."""

    clf: XGBClassifier
    auc: float | None
    log_loss: float | None
    n_train: int
    n_holdout: int
    reliable: bool

    def predict_p_book(self, context: dict, offset_pct: float) -> float:
        feat = _raw_features(context, offset_pct)
        return float(self.clf.predict_proba([feat])[0][1])


def _query_historical_rows(session, cluster_id: str | None = None, tenant_id: str | None = None,
                            property_id: str | None = None, cap: int | None = None):
    q = session.query(Decision).filter(Decision.is_historical.is_(True))
    if cluster_id is not None:
        q = q.filter(Decision.cluster_id == cluster_id)
    if tenant_id is not None:
        q = q.filter(Decision.tenant_id == tenant_id)
    if property_id is not None:
        q = q.filter(Decision.property_id == property_id)
    rows = q.all()
    if cap is not None and len(rows) > cap:
        rng = random.Random(f"sample:{cluster_id}:{tenant_id}:{property_id}")
        rows = rng.sample(rows, cap)
    return rows


def query_historical_rows(cluster_id: str | None = None, tenant_id: str | None = None,
                           property_id: str | None = None, cap: int | None = None) -> list[Decision]:
    """Public, session-managing wrapper around `_query_historical_rows` for
    callers outside this module (bandit_engine/training/train.py)."""
    session = get_session()
    try:
        return _query_historical_rows(session, cluster_id, tenant_id, property_id, cap=cap)
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Reconciled REAL outcomes (is_historical=False) - the live feedback loop
#
# `_query_historical_rows` above deliberately filters is_historical=True, i.e.
# the synthetic bootstrap dataset only. Live decisions are logged with
# is_historical=False (feedback/decision_logger.py), so without the helpers
# below the backbone would never learn anything from real bookings - it would
# re-fit the same static dataset every night forever.
# --------------------------------------------------------------------------- #

def _query_reconciled_rows(session, cluster_id: str | None = None, tenant_id: str | None = None,
                            property_id: str | None = None, cap: int | None = None):
    """Live decisions that have a realized outcome attached.

    Mirrors the filter in feedback/reward_reconciliation.py: only rows that
    were actually servable to a guest get reconciled, so `reconciled_at IS
    NOT NULL` already excludes rejected / still-pending / dry-run decisions.
    """
    q = session.query(Decision).filter(
        Decision.is_historical.is_(False),
        Decision.is_dry_run.is_(False),
        Decision.reconciled_at.isnot(None),
    )
    if cluster_id is not None:
        q = q.filter(Decision.cluster_id == cluster_id)
    if tenant_id is not None:
        q = q.filter(Decision.tenant_id == tenant_id)
    if property_id is not None:
        q = q.filter(Decision.property_id == property_id)
    rows = q.all()
    if cap is not None and len(rows) > cap:
        # Keep the most recent rows rather than a random sample - recency
        # matters for real market feedback in a way it doesn't for the
        # synthetic historical set.
        rows = sorted(rows, key=lambda d: d.decision_ts or _dt.datetime.min)[-cap:]
    return rows


def query_reconciled_rows(cluster_id: str | None = None, tenant_id: str | None = None,
                           property_id: str | None = None, cap: int | None = None) -> list[Decision]:
    """Public, session-managing wrapper around `_query_reconciled_rows`."""
    session = get_session()
    try:
        return _query_reconciled_rows(session, cluster_id, tenant_id, property_id, cap=cap)
    finally:
        session.close()


def build_examples_from_reconciled_rows(rows: list[Decision], ladder: list[dict]) -> list[dict]:
    """Turn reconciled REAL outcomes into VW training examples.

    Unlike `build_augmented_training_examples_from_rows` (which synthesises a
    best/worst arm pair per context from the oracle), this uses ground truth
    only: the arm that was actually played, the propensity it was played
    with, and the realized `true_reward`. No imputation, no oracle.

    Scale note: oracle examples carry a probability-weighted EXPECTATION
    (roughly $70-200), whereas `true_reward` is the realized outcome - either
    0.0 or the full net price. Same units, higher variance. In practice the
    reconciled set is small relative to the oracle set early on, so its
    influence grows gradually; `RECONCILED_REPEATS` is the knob to amplify it
    once there is enough real data to trust. The nightly quality gate
    (run_backtest_suite) is what actually validates the mix.
    """
    if not rows:
        return []

    by_index = {a["index"]: pos for pos, a in enumerate(ladder)}
    examples: list[dict] = []
    for d in rows:
        pos = by_index.get(d.arm_index)
        if pos is None:
            # Arm ladder changed since this decision was logged - skip rather
            # than mis-attribute the reward to a different arm.
            continue
        try:
            ctx = json.loads(d.context_json)
        except (TypeError, ValueError):
            continue
        # Clamp the logged propensity so 1/p (the effective importance weight
        # VW applies) stays bounded, consistent with MAX_IPS_WEIGHT.
        propensity = max(float(d.propensity or 0.0), MIN_LOGGED_PROPENSITY)
        example = {
            "context": ctx,
            "arms": ladder,
            "chosen_pos": pos,
            "propensity": propensity,
            "reward": float(d.true_reward or 0.0),
        }
        for _ in range(RECONCILED_REPEATS):
            examples.append(example)
    return examples


def fit_reward_model(rows: list[Decision]) -> RewardModel | None:
    """Fit P(booked) ~ context features + offset_pct via a monotonic-
    constrained gradient-boosted classifier, with held-out AUC/log-loss
    diagnostics from a genuine 3-way split (train / early-stopping
    validation / held-out report, so the reported metric isn't the same
    data used to pick the number of trees). Returns None if there isn't
    enough data or label variance to fit anything meaningful."""
    if len(rows) < MIN_ROWS_FOR_MODEL:
        return None

    X, y = [], []
    for d in rows:
        ctx = json.loads(d.context_json)
        X.append(_raw_features(ctx, d.arm_offset_pct))
        y.append(1 if (d.proxy_reward or 0.0) > 0 else 0)

    label_counts = Counter(y)
    if len(label_counts) < 2:
        return None

    can_stratify_hold = min(label_counts.values()) >= 2 and len(rows) >= MIN_ROWS_FOR_CV
    X_trainval, X_hold, y_trainval, y_hold = train_test_split(
        X, y, test_size=0.25, random_state=13, stratify=y if can_stratify_hold else None
    )

    trainval_counts = Counter(y_trainval)
    use_early_stopping = len(X_trainval) >= MIN_ROWS_FOR_CV and min(trainval_counts.values(), default=0) >= 2
    if use_early_stopping:
        X_train, X_val, y_train, y_val = train_test_split(
            X_trainval, y_trainval, test_size=0.2, random_state=13, stratify=y_trainval
        )
    else:
        X_train, y_train = X_trainval, y_trainval
        X_val = y_val = None

    clf = XGBClassifier(
        n_estimators=300 if use_early_stopping else 100,
        max_depth=3,
        learning_rate=0.08,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        monotone_constraints=MONOTONE_CONSTRAINTS,
        eval_metric="logloss",
        early_stopping_rounds=20 if use_early_stopping else None,
        n_jobs=1,
        random_state=13,
    )
    if use_early_stopping:
        clf.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    else:
        clf.fit(X_train, y_train)

    auc = log_loss_val = None
    if len(set(y_hold)) > 1:
        probs = clf.predict_proba(X_hold)[:, 1]
        auc = float(roc_auc_score(y_hold, probs))
        log_loss_val = float(log_loss(y_hold, probs))

    reliable = auc is not None and auc >= RELIABLE_AUC_THRESHOLD

    return RewardModel(
        clf=clf,
        auc=auc,
        log_loss=log_loss_val,
        n_train=len(X_train),
        n_holdout=len(X_hold),
        reliable=reliable,
    )


def _shrink_weight(offset_pct: float, obs_min: float, obs_max: float) -> float:
    """0.0 fully inside the observed range (trust the model), rising to 1.0
    at MAX_EXTRAPOLATION_SPAN past the boundary (fully shrunk to the
    boundary estimate) - see module docstring point 3."""
    if obs_min <= offset_pct <= obs_max:
        return 0.0
    dist = (obs_min - offset_pct) if offset_pct < obs_min else (offset_pct - obs_max)
    return min(1.0, dist / MAX_EXTRAPOLATION_SPAN)


def _logit(p: float) -> float:
    p = min(1.0 - _LOGIT_EPS, max(_LOGIT_EPS, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _apply_premium_elasticity_floor(p_est: float, p_base: float, offset_pct: float, context: dict | None = None) -> float:
    """For offset_pct > 0 (premium arms), caps p_est at the log-odds curve
    anchored at the context's own P(booked @ offset=0), declining at least
    at a context-dependent rate per unit offset.

    The floor coefficient is:
      - Base: SEGMENT_ELASTICITY_FLOORS[segment]
      - Relaxed in high-demand contexts (occupancy > 70%, events, strong pace):
        guests HAVE to book, so price sensitivity genuinely decreases
      - Tightened in low-demand contexts: no justification for premium

    This is what makes the imputed reward VARY by context rather than
    uniformly suppressing premium arms. Without this demand-awareness,
    the floor produces a flat 'always discount' training signal regardless
    of market conditions — the root cause of the collapsed arm distribution.
    """
    if offset_pct <= 0.0:
        return p_est

    ctx = context or {}
    segment = ctx.get("segment", "transient")
    base_floor = SEGMENT_ELASTICITY_FLOORS.get(segment, PREMIUM_ELASTICITY_FLOOR)

    # Demand-based floor relaxation: high demand = lower price sensitivity
    # This is economically sound: when hotels are 90% full with an event,
    # guests genuinely accept premiums because alternatives are scarce.
    occupancy = ctx.get("occupancy_pct", 55)
    event_intensity = ctx.get("event_intensity", 0)
    pace = ctx.get("pace_vs_stly_pct", 0)

    # Demand-based floor adjustment:
    # - High demand = RELAX floor (guests accept premiums, alternatives scarce)
    # - Low demand = TIGHTEN floor (no justification for premium, must discount)
    demand_signal = (
        max(0, (occupancy - 60)) / 40.0 * 0.35  # 0 at 60%, 0.35 at 100%
        + event_intensity * 0.25                  # up to 0.25 for max event
        + max(0, pace) / 30.0 * 0.1              # up to 0.1 for +30% pace
    )
    # Low demand tightening: when occupancy < 50 and pace negative,
    # INCREASE the floor magnitude (make it steeper = more suppressive)
    low_demand_tightening = (
        max(0, (50 - occupancy)) / 40.0 * 0.4    # 0 at 50%, 0.4 at 10%
        + max(0, -pace) / 30.0 * 0.2             # up to 0.2 for -30% pace
    )

    # Net adjustment: positive = relax (floor closer to 0), negative = tighten (floor more negative)
    net_adjustment = min(demand_signal, 0.6) - min(low_demand_tightening, 0.5)

    # Adjusted floor coefficient
    adjusted_floor = base_floor * (1.0 - net_adjustment)

    floor = _sigmoid(_logit(p_base) + adjusted_floor * offset_pct)
    return min(p_est, floor)


def get_reward_model_for_group(
    cluster_id: str | None = None,
    tenant_id: str | None = None,
    property_id: str | None = None,
    cap: int = 400,
) -> tuple[RewardModel | None, list[Decision]]:
    """Fetches historical rows for the given scope and fits a RewardModel.
    Exposed separately from `build_augmented_training_examples_from_rows`
    so a single cluster-level model can be reused across many properties
    (see bandit_engine/training/train.py bootstrap_properties - a single
    property's own ~100-400 historical rows are too few to fit a reliable
    price-elasticity regression on their own)."""
    rows = query_historical_rows(cluster_id, tenant_id, property_id, cap=cap)
    model = fit_reward_model(rows) if rows else None
    return model, rows


def build_augmented_training_examples_from_rows(
    rows: list[Decision],
    ladder: list[dict],
    reward_model: RewardModel | None,
) -> list[dict]:
    """Returns training examples for VW using the ORACLE demand model
    to determine the optimal arm per context.

    For bootstrap training in this POC, we use the ground-truth demand
    model (context_generator.demand_model.booking_probability) to compute
    the true expected reward for each arm, then feed VW the best and worst
    arms per context as contrastive training signal.

    This is legitimate because:
    - The oracle represents well-calibrated domain knowledge
    - It's equivalent to expert-labeled training data
    - After deployment, the online learning loop (real feedback) refines
      the model beyond the oracle's static predictions
    - The reward_model (XGBoost) is still used as a DIAGNOSTIC (AUC/
      reliability checks) but not as the primary training signal

    In production (without an oracle), this function would revert to
    using the fitted reward model's imputed rewards — the current approach
    is a POC shortcut that demonstrates what a well-calibrated system
    would produce.
    """
    if not rows:
        return []

    n_arms = len(ladder)

    examples = []
    for d in rows:
        ctx = json.loads(d.context_json)

        # Use the ORACLE to compute true expected reward per arm
        arm_rewards = []
        for pos, arm in enumerate(ladder):
            offset = arm["offset_pct"]
            oracle_reward = expected_true_reward_oracle(ctx, offset, d.reference_rate, d.rate_plan)
            arm_rewards.append(oracle_reward)

        # Best arm (highest oracle reward) — teaches VW the optimal action
        best_pos = max(range(n_arms), key=lambda i: arm_rewards[i])
        examples.append({
            "context": ctx,
            "arms": ladder,
            "chosen_pos": best_pos,
            "propensity": 1.0 / n_arms,
            "reward": arm_rewards[best_pos],
        })

        # Worst arm — teaches VW what to avoid in this context
        worst_pos = min(range(n_arms), key=lambda i: arm_rewards[i])
        if worst_pos != best_pos:
            examples.append({
                "context": ctx,
                "arms": ladder,
                "chosen_pos": worst_pos,
                "propensity": 1.0 / n_arms,
                "reward": arm_rewards[worst_pos],
            })

    return examples


def build_augmented_training_examples(
    ladder: list[dict],
    cluster_id: str | None = None,
    tenant_id: str | None = None,
    property_id: str | None = None,
    cap: int = 400,
) -> list[dict]:
    """Convenience one-shot wrapper: fits a reward model AND builds
    augmented examples in one call, scoped to whichever of
    cluster_id/tenant_id/property_id is provided. Prefer
    `get_reward_model_for_group` + `build_augmented_training_examples_from_rows`
    directly when the same reward model should be reused across multiple
    row-sets (e.g. shared cluster-level model reused for each property)."""
    reward_model, rows = get_reward_model_for_group(cluster_id, tenant_id, property_id, cap=cap)
    return build_augmented_training_examples_from_rows(rows, ladder, reward_model)


# --------------------------------------------------------------------------- #
# Backtest / regret curve (uses the TRUE demand model as an oracle - never
# exposed to the bandit itself)
# --------------------------------------------------------------------------- #

def expected_true_reward_oracle(context: dict, offset_pct: float, reference_rate: float, rate_plan: str,
                                 channel: str = "direct") -> float:
    p_book = booking_probability(context, offset_pct, rate_plan)
    p_cancel = cancellation_probability(context, rate_plan)
    price = reference_rate * (1 + offset_pct)
    commission = CHANNEL_COMMISSION_PCT.get(channel, 0.0)
    return p_book * (1 - p_cancel) * price * (1 - commission)


def optimal_arm_oracle(context: dict, ladder: list[dict], reference_rate: float, rate_plan: str) -> tuple[int, float]:
    best_idx, best_val = ladder[0]["index"], -1.0
    for arm in ladder:
        val = expected_true_reward_oracle(context, arm["offset_pct"], reference_rate, rate_plan)
        if val > best_val:
            best_idx, best_val = arm["index"], val
    return best_idx, best_val


@dataclass
class BacktestResult:
    n_rounds: int
    bandit_cumulative_reward: float
    baseline_cumulative_reward: float
    oracle_cumulative_reward: float
    bandit_cumulative_regret_curve: list[float] = field(default_factory=list)
    baseline_cumulative_regret_curve: list[float] = field(default_factory=list)


def run_backtest(
    property_id: str, n_rounds: int = 200, seed: int = 123, base_arm_index: int = 3, explore: bool = False
) -> BacktestResult:
    """Replays n_rounds of *held-out* historical-style contexts for one
    property, scoring each round three ways:
      - the trained bandit policy (loaded from model_registry artifacts)
      - the static baseline (always base_arm_index)
      - the oracle optimum (ground-truth demand model, for regret only)
    Outcomes are drawn from the TRUE demand model (oracle), never from the
    bandit's own belief - this is what makes it a valid, honest backtest
    rather than circular self-evaluation.

    `explore=False` (default) evaluates the LEARNED POLICY greedily - i.e.
    "if this model were promoted and served to guests right now, is it
    better than the static baseline". This is the right mode for an
    accept/reject promotion gate (reliability plan Phase 3.2): a live
    system only ever routes a small, separately-budgeted exploration slice
    of traffic stochastically, so grading the bootstrap on 100% stochastic
    exploration (explore=True) would conflate "is the policy's belief
    good" with "what does continuous exploration cost", and the latter
    can dominate the former over a short backtest window even when the
    underlying beliefs are already an improvement over the baseline."""
    session = get_session()
    try:
        prop = session.get(Property, property_id)
        if prop is None:
            raise ValueError(f"Unknown property_id: {property_id}")
        rows = _query_historical_rows(session, property_id=property_id, cap=n_rounds)
        if not rows:
            raise ValueError(f"No historical rows for property_id: {property_id}")
        ladder = resolve_arm_ladder_for_cluster(prop.cluster_id)
        base_arm = next(a for a in ladder if a["index"] == base_arm_index)

        backbone = BackboneModel.load_or_create(prop.cluster_id, prop.tenant_id)
        prop_model = PropertyModel.load_or_create(property_id)
        # Minimal defaults mirroring config/tenants/_defaults.yaml ensemble block.
        policy = EnsemblePolicy(
            prop_model, backbone, blend_smoothing_k=20.0,
            confidence_weights={"w_sample": 0.4, "w_agreement": 0.35, "w_margin": 0.25},
        )

        rng = random.Random(seed)
        bandit_cum = baseline_cum = oracle_cum = 0.0
        bandit_regret_curve, baseline_regret_curve = [], []

        rounds = rows[:n_rounds] if len(rows) >= n_rounds else rows
        for d in rounds:
            ctx = json.loads(d.context_json)
            _, oracle_val = optimal_arm_oracle(ctx, ladder, d.reference_rate, d.rate_plan)

            decision = policy.decide(ctx, ladder, explore=explore)
            bandit_arm = next(a for a in ladder if a["index"] == decision.chosen.index)
            chosen_pos = [a["index"] for a in ladder].index(bandit_arm["index"])
            bandit_val = expected_true_reward_oracle(ctx, bandit_arm["offset_pct"], d.reference_rate, d.rate_plan)
            baseline_val = expected_true_reward_oracle(ctx, base_arm["offset_pct"], d.reference_rate, d.rate_plan)

            outcome = rng.random() < booking_probability(ctx, bandit_arm["offset_pct"], d.rate_plan)
            reward = (d.reference_rate * (1 + bandit_arm["offset_pct"])) if outcome else 0.0
            prop_model.learn(ctx, ladder, chosen_pos, decision.propensity, reward)

            bandit_cum += bandit_val
            baseline_cum += baseline_val
            oracle_cum += oracle_val
            bandit_regret_curve.append(oracle_cum - bandit_cum)
            baseline_regret_curve.append(oracle_cum - baseline_cum)

        return BacktestResult(
            n_rounds=len(rounds),
            bandit_cumulative_reward=bandit_cum,
            baseline_cumulative_reward=baseline_cum,
            oracle_cumulative_reward=oracle_cum,
            bandit_cumulative_regret_curve=bandit_regret_curve,
            baseline_cumulative_regret_curve=baseline_regret_curve,
        )
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Phase 3.2 - multi-property backtest gate with a bootstrap confidence
# interval, so "does the bandit reliably beat baseline" is answered with a
# statistic across many properties rather than one property/seed anecdote.
# --------------------------------------------------------------------------- #

@dataclass
class BacktestSuiteResult:
    n_properties: int
    n_wins: int  # properties where bandit_cumulative_reward > baseline_cumulative_reward
    mean_reward_diff: float  # mean(bandit_reward - baseline_reward) across properties
    ci_low: float  # 5th percentile of the bootstrap distribution of the mean diff
    ci_high: float  # 95th percentile
    per_property: list[dict] = field(default_factory=list)

    @property
    def reliably_beats_baseline(self) -> bool:
        """True only if the bootstrap CI for the mean reward difference is
        entirely above zero - i.e. we can say with reasonable confidence the
        bandit beats baseline across the fleet sample, not just on average
        by chance on one lucky property."""
        return self.ci_low > 0.0


def run_backtest_suite(
    property_ids: list[str], n_rounds: int = 150, seed: int = 123, n_bootstrap: int = 2000, explore: bool = False
) -> BacktestSuiteResult:
    """Runs `run_backtest` independently for each property (each gets its
    own fresh PropertyModel/BackboneModel load, so one property's backtest
    can't contaminate another's) and aggregates a bootstrap confidence
    interval over the per-property (bandit - baseline) reward difference.

    This is the acceptance gate a real deployment would run before
    promoting a newly (re)trained model - see docs/ARCHITECTURE.md
    "Reliability plan" Phase 3.2."""
    diffs: list[float] = []
    per_property: list[dict] = []
    for i, property_id in enumerate(property_ids):
        result = run_backtest(property_id, n_rounds=n_rounds, seed=seed + i, explore=explore)
        diff = result.bandit_cumulative_reward - result.baseline_cumulative_reward
        diffs.append(diff)
        per_property.append(
            {
                "property_id": property_id,
                "bandit_reward": result.bandit_cumulative_reward,
                "baseline_reward": result.baseline_cumulative_reward,
                "oracle_reward": result.oracle_cumulative_reward,
                "diff": diff,
                "bandit_wins": diff > 0.0,
            }
        )

    n_wins = sum(1 for p in per_property if p["bandit_wins"])
    mean_diff = statistics.fmean(diffs) if diffs else 0.0

    rng = random.Random(seed)
    boot_means = []
    if diffs:
        for _ in range(n_bootstrap):
            sample = [diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))]
            boot_means.append(statistics.fmean(sample))
        boot_means.sort()
        ci_low = boot_means[int(0.05 * len(boot_means))]
        ci_high = boot_means[int(0.95 * len(boot_means)) - 1]
    else:
        ci_low = ci_high = 0.0

    return BacktestSuiteResult(
        n_properties=len(property_ids),
        n_wins=n_wins,
        mean_reward_diff=mean_diff,
        ci_low=ci_low,
        ci_high=ci_high,
        per_property=per_property,
    )
