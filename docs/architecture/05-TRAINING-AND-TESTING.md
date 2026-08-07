# 05 - Training and Testing

## Training Lifecycle Overview

The system has three distinct training phases, each with different data sources, update frequency, and scope:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         TRAINING LIFECYCLE                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: BOOTSTRAP (one-time)                                               │
│  ═══════════════════════════════                                             │
│  Trigger: First deployment / new property onboarding                         │
│  Data:    Synthetic historical data (POC) or imported PMS history (prod)     │
│  Models:  ALL backbones + ALL property models                                │
│  Script:  python -m orchestration.pipelines.run_bootstrap                    │
│                                                                              │
│  PHASE 2: NIGHTLY RETRAIN (scheduled, batch)                                 │
│  ═══════════════════════════════════════════                                  │
│  Trigger: Cron/scheduler (daily)                                             │
│  Data:    Reconciled real decisions + original historical data                │
│  Models:  ALL backbones + ALL property models (with quality gate)             │
│  Script:  python -m orchestration.pipelines.run_nightly                      │
│                                                                              │
│  PHASE 3: ONLINE LEARNING (continuous, per-decision)                         │
│  ═══════════════════════════════════════════════════                          │
│  Trigger: Each reconciled decision (stay_date has passed)                    │
│  Data:    Single (context, arm, true_reward) tuple                           │
│  Models:  ONLY the specific PropertyModel (isolated)                         │
│  Code:    feedback/reward_reconciliation.py → PropertyModel.learn()          │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Bootstrap Training

### Purpose
Initialize all models from scratch so the system isn't a blank random slate on day one.

### Pipeline Flow

```
orchestration/pipelines/run_bootstrap.py
│
├── 1. generate_all()  [context_generator/multi_chain_synthetic_data.py]
│   ├── For each tenant:
│   │   ├── For each brand → region → cluster:
│   │   │   ├── Generate N properties with attributes (base_bar, etc.)
│   │   │   └── For each property:
│   │   │       ├── Generate ~150-400 historical decision rows
│   │   │       ├── Context built via context_builder.py (correlated signals)
│   │   │       ├── Arm selection: ~85% base rate, ~15% adjacent exploration
│   │   │       └── Outcome via demand_model (ground-truth oracle)
│   │   └── Persist to DB: Property, RoomType, RatePlan, Decision rows
│   └── Return generation summary
│
└── 2. bootstrap_all()  [bandit_engine/training/train.py]
    │
    ├── bootstrap_backbones()
    │   ├── Identify all (cluster_id, tenant_id) pairs from DB
    │   ├── For each pair:
    │   │   ├── Query historical rows (cap: 8000 per cluster-tenant)
    │   │   ├── Fit cluster-level reward model (XGBoost, see below)
    │   │   ├── Generate augmented training examples (oracle-based)
    │   │   ├── Create BackboneModel (5 VW workspaces)
    │   │   ├── learn_batch(examples) with 3 passes over data
    │   │   └── Save versioned artifacts
    │   └── Return reward_model_cache (shared with property bootstrap)
    │
    └── bootstrap_properties(reward_model_cache)
        └── For each property:
            ├── Query property-specific rows (cap: 1500)
            ├── REUSE cluster's reward model (not re-fitted per property)
            ├── Generate augmented examples from property's own contexts
            ├── Create PropertyModel (single VW workspace)
            ├── learn() each example with count_as_observation=False
            └── Save versioned artifacts
```

### Why `count_as_observation=False`?

Bootstrap pretraining updates VW weights (so the property isn't random), but deliberately does NOT increment `n_observations`. This is critical because:

- `n_observations` drives the credibility weight: `w = n / (n + k)`
- If 400 bootstrap examples counted as observations, `w = 400/(400+20) = 0.95`
- The property would immediately be 95% self-reliant with zero REAL feedback
- Defeats the entire purpose of the backbone safety net for cold-start

Instead, only **real reconciled decisions** (Phase 3) increment `n_observations`.

---

## Phase 2: Nightly Retrain

### Purpose
Incorporate fresh real-world feedback into all models, with a quality gate to prevent regressions.

### Pipeline Flow

```
orchestration/pipelines/run_nightly.py
│
├── Step 1: RECONCILE
│   └── reconcile_pending_decisions()
│       ├── Find decisions where stay_date <= today AND reconciled_at IS NULL
│       ├── Filter: only "approved" or "auto_published" (never rejected/pending)
│       ├── Simulate realized outcome (booked? cancelled? channel?)
│       ├── Compute true_reward = price * booked * (1-cancel) * (1-commission)
│       ├── Feed PropertyModel.learn() (online update, increments n_observations)
│       └── Save property models
│
├── Step 2: RETRAIN
│   ├── bootstrap_backbones() - full re-fit from all available data
│   │   └── Creates NEW versioned artifacts (old versions preserved)
│   └── bootstrap_properties() - full re-fit of all property models
│       └── Same process as initial bootstrap, but with more data now
│
└── Step 3: QUALITY GATE
    ├── Sample 6 properties for backtest (fixed seed for reproducibility)
    ├── Run backtest suite (see "Testing" section below)
    │
    ├── IF reliably_beats_baseline = True:
    │   └── PROMOTE: new model versions stay as "current" (already saved)
    │
    └── IF reliably_beats_baseline = False:
        └── ROLLBACK: revert ALL backbone + property models to previous version
            ├── For each backbone: versioning.rollback(base_dir)
            ├── For each property: versioning.rollback(base_dir)
            └── Log warning (system continues on prior model)
```

### Quality Gate Logic

```python
# The gate blocks promotion if the new model doesn't reliably beat baseline
suite_result = run_backtest_suite(sample_property_ids, n_rounds=150)

# suite_result contains:
#   reliably_beats_baseline: bool  (CI_low > 0)
#   mean_reward_diff: float        (avg reward_bandit - reward_baseline)
#   ci_low, ci_high: float         (bootstrap confidence interval)
#   n_wins: int                    (properties where bandit > baseline)
#   n_properties: int              (total tested)
```

---

## Reward Model (XGBoost) - The Training Signal Generator

### Purpose
The reward model is NOT the production scoring model. It's used during training to **impute rewards for arms that were never tried** in historical data. This is necessary because historical logs show near-zero exploration (85% base rate).

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│              Reward Model (fit_reward_model)                       │
│                                                                   │
│  Target:   P(booked) ~ context_features + offset_pct             │
│  Model:    XGBClassifier with monotonic constraints               │
│  Split:    3-way: Train / Early-Stop-Val / Held-Out-Report       │
│                                                                   │
│  Feature Vector (per arm evaluation):                             │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │ occupancy_pct, adr_trend, pace, pickup, remaining_inv,  │     │
│  │ compset_index, compset_trend, compset_dispersion,        │     │
│  │ event_intensity, event_flag,                             │     │
│  │ offset_pct,                          ← MONOTONE (-1)    │     │
│  │ occupancy*offset, event*offset,      ← MONOTONE (-1)    │     │
│  │ pace*offset, pickup*offset,          ← MONOTONE (-1)    │     │
│  │ segment_elasticity*offset            ← MONOTONE (-1)    │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                   │
│  Key constraints:                                                 │
│  • monotone_constraints: offset_pct and all interactions are      │
│    constrained to be NON-INCREASING (raising price never          │
│    increases booking probability - law of demand)                  │
│  • premium_elasticity_floor: context-conditioned minimum          │
│    log-odds decay for premium arms (prevents "always pick         │
│    most expensive" failure mode)                                   │
│  • Segment-aware floors:                                          │
│      corporate: -1.3 (least elastic)                              │
│      group:     -1.6                                              │
│      transient: -2.0 (moderate)                                   │
│      leisure:   -2.6 (most elastic)                               │
│                                                                   │
│  Reliability checks:                                              │
│  • AUC >= 0.55 on held-out set → reliable = True                 │
│  • Below that → diagnostics flag unreliable fit                   │
└──────────────────────────────────────────────────────────────────┘
```

### Oracle-Based Training (POC Shortcut)

In this POC, training examples are generated using the **ground-truth demand oracle** (`context_generator/demand_model.py`), not the XGBoost reward model:

```
For each historical context row:
  1. Compute true expected reward for ALL 9 arms via oracle:
     expected_reward(arm) = P(booked|context, offset) * price * (1-cancel) * (1-commission)
  
  2. Identify BEST arm (highest oracle reward) → teaches VW the optimal action
  3. Identify WORST arm (lowest oracle reward) → teaches VW what to avoid
  
  4. Feed both as contrastive training examples to VW:
     - Best arm example:  reward = oracle_reward[best], propensity = 1/9
     - Worst arm example: reward = oracle_reward[worst], propensity = 1/9
```

**Why this is legitimate:** The oracle represents well-calibrated domain knowledge (equivalent to expert-labeled data). After deployment, the online learning loop refines beyond the oracle's static predictions.

**In production** (without an oracle): The XGBoost reward model would be used as the primary training signal, with its monotonic constraints and doubly-robust corrections compensating for sparse exploration in historical logs.

---

## VW Training Details

### BackboneModel Training

```python
# 5 VW workspaces, Poisson(1) online-bagging
# Each member independently sees a resampled version of the data

for _pass in range(3):  # 3 passes over data to strengthen signal
    for vw in self.members:
        for example in examples:
            weight = Poisson(1)  # online-bagging resample weight
            if weight == 0: continue
            
            # VW CB_ADF format:
            # shared |c occupancy_pct:75 pace_vs_stly_pct:12 event_flag ...
            # {chosen_pos}:{cost}:{propensity} |a arm_idx_3 arm_label_Base_Rate
            # |a arm_idx_4 arm_label_Slight_Premium
            # ... (all 9 arms)
            
            for _ in range(weight):
                vw.learn(example)
```

### PropertyModel Training (Bootstrap)

```python
# Single VW workspace, no bagging (simpler)
for example in examples:
    model.learn(
        context=example["context"],
        arms=example["arms"],
        chosen_pos=example["chosen_pos"],
        propensity=example["propensity"],
        reward=example["reward"],
        count_as_observation=False,  # CRITICAL: don't inflate credibility weight
    )
```

### PropertyModel Training (Online / Post-Reconciliation)

```python
# Single decision at a time, from reward_reconciliation.py
model.learn(
    context=context_from_decision,
    arms=ladder_for_cluster,
    chosen_pos=position_of_arm_that_was_actually_played,
    propensity=logged_propensity,
    reward=true_reward,  # real outcome
    count_as_observation=True,  # THIS one counts - earned trust
)
```

---

## Testing: Backtest Suite

### Purpose
Validates that a trained policy actually outperforms the static baseline (always choosing Base Rate / 0% offset) before promoting it to production.

### Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     Backtest Suite (run_backtest_suite)                    │
│                                                                          │
│  For each property in sample:                                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  run_backtest(property_id, n_rounds=150)                           │ │
│  │                                                                    │ │
│  │  For each round:                                                   │ │
│  │    1. Generate a random context (demand scenario)                  │ │
│  │    2. Score via trained EnsemblePolicy → bandit_arm                │ │
│  │    3. Static baseline → always arm_3 (Base Rate, 0%)               │ │
│  │    4. Oracle evaluates BOTH:                                       │ │
│  │       reward_bandit  = oracle_reward(context, bandit_offset)       │ │
│  │       reward_baseline = oracle_reward(context, 0.0)                │ │
│  │    5. Accumulate: Σ(reward_bandit - reward_baseline)               │ │
│  │                                                                    │ │
│  │  Result: total_reward_bandit vs total_reward_baseline              │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Aggregate across properties:                                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  - mean_reward_diff = avg(bandit_total - baseline_total)           │ │
│  │  - Bootstrap CI (95%): resample properties, recompute mean         │ │
│  │  - reliably_beats_baseline = (CI_low > 0)                         │ │
│  │  - n_wins = count(properties where bandit > baseline)             │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │  Quality Gate Decision:                  │                            │
│  │                                         │                            │
│  │  CI_low > 0 ?                           │                            │
│  │    YES → PROMOTE new model              │                            │
│  │    NO  → ROLLBACK to previous version   │                            │
│  └─────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### What the Oracle Evaluates

```python
def expected_true_reward_oracle(context, offset_pct, reference_rate, rate_plan):
    """True expected reward using the ground-truth demand model.
    
    reward = price * P(booked) * (1 - P(cancel)) * (1 - commission_pct)
    
    This oracle is NEVER exposed to the bandit - only used for evaluation.
    """
    price = reference_rate * (1 + offset_pct)
    p_book = booking_probability(context, offset_pct, rate_plan)   # true elasticity
    p_cancel = cancellation_probability(context, offset_pct)
    commission = CHANNEL_COMMISSION_PCT  # e.g., 15% for OTA
    
    return price * p_book * (1 - p_cancel) * (1 - commission)
```

### Interpreting Backtest Results

| Result | Meaning | Action |
|--------|---------|--------|
| CI = [+5.2, +12.8] | Model reliably outperforms baseline by $5-13 per decision | PROMOTE |
| CI = [-1.2, +8.5] | Inconclusive - CI crosses zero | ROLLBACK (conservative) |
| CI = [-6.0, -1.5] | Model is WORSE than baseline | ROLLBACK |
| n_wins = 6/6 | Every sampled property benefits | Strong confidence |
| n_wins = 3/6 | Mixed results across properties | Investigate per-cluster |

---

## Model Versioning and Rollback

### Version Lifecycle

```
                     save()              save()              save()
                       │                   │                   │
         ┌─────────────v───────┐  ┌───────v───────┐  ┌───────v───────┐
         │ v_20240614_120000   │  │ v_20240615_... │  │ v_20240616_... │
         │  (day 1 bootstrap)  │  │  (nightly #1)  │  │  (nightly #2)  │
         └─────────────────────┘  └───────────────┘  └───────────────┘
                                                              │
                                                     current.txt ──> "v_20240616_..."
```

### Rollback Mechanics

```python
# On quality gate failure:
for each backbone_dir:
    rollback(base_dir)  # current.txt → previous version tag

for each property_dir:
    rollback(base_dir)  # current.txt → previous version tag

# Result: system immediately serves previous (known-good) model
# The failed version directory remains on disk (can be investigated)
```

### Pruning

```python
MAX_VERSIONS_KEPT = 5  # keep last 5 versions, delete older
prune_old_versions(base_dir)  # called after every save()
# Never deletes the current version, even if it's old
```

---

## Testing Strategy

### Unit Tests (existing `tests/` directory)

| Test File | Covers |
|-----------|--------|
| `test_confidence.py` | Confidence score calculation |
| `test_config_loader.py` | YAML loading, deep-merge, extends mechanism |
| `test_guardrails.py` | Guardrail rule evaluation, action masking |
| `test_offline_eval.py` | Reward model fitting, augmented example generation |
| `test_reference_rate.py` | Rate composition formula |

### Integration Testing (recommended additions)

| Test | Purpose |
|------|---------|
| `test_api.py` | FastAPI TestClient - endpoint contracts, status codes |
| `test_reconciliation.py` | Reward reconciliation correctness |
| `test_pipeline_e2e.py` | Full bootstrap → score → reconcile → retrain cycle |
| `test_quality_gate.py` | Gate promote/rollback under various scenarios |

### Backtest as Regression Test

The quality gate itself serves as an automated regression test:
- Every nightly retrain validates the model hasn't regressed
- If a code change breaks model quality, the next nightly run will catch it
- System automatically rolls back to the last known-good version

---

## Training Data Flow Summary

```
┌──────────────────┐     ┌───────────────────┐     ┌──────────────────┐
│  Historical Data │     │   Real Decisions   │     │   Oracle Demand  │
│  (synthetic/PMS) │     │ (reconciled, live) │     │   Model (test)   │
└────────┬─────────┘     └─────────┬─────────┘     └────────┬─────────┘
         │                         │                         │
         │  query_historical_rows  │  reconcile_pending      │  backtest only
         │                         │                         │
         v                         v                         v
┌──────────────────────────────────────────────────────────────────────┐
│                     TRAINING PIPELINE                                  │
│                                                                      │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────────────────┐ │
│  │ Reward Model │  │ Augmented Example │  │ VW learn_batch /     │ │
│  │ (XGBoost)    │->│ Generator         │->│ learn (online)       │ │
│  │              │  │ (oracle-based)    │  │                      │ │
│  └──────────────┘  └───────────────────┘  └──────────┬───────────┘ │
│                                                       │             │
└───────────────────────────────────────────────────────┼─────────────┘
                                                        │
                                                        v
                                               ┌────────────────┐
                                               │ Model Artifacts │
                                               │ (versioned)     │
                                               └───────┬────────┘
                                                       │
                                            ┌──────────┴──────────┐
                                            v                     v
                                   ┌──────────────┐      ┌──────────────┐
                                   │  Backtest    │      │  Production  │
                                   │  (quality    │      │  Scoring     │
                                   │   gate)      │      │              │
                                   └──────────────┘      └──────────────┘
```

---

## Key Design Decisions in Training

| Decision | Rationale |
|----------|-----------|
| Oracle-based examples (POC) | Ground-truth demand model gives perfect training signal; in production, use reward model with uncertainty handling |
| 3 passes over training data | VW's online learning needs repetition to converge with diverse contexts |
| Poisson(1) bagging | Each backbone member sees a different resample → disagreement measures genuine uncertainty |
| Monotonic XGBoost constraints | Structural guarantee: higher price can't increase booking probability (law of demand) |
| Context-conditioned elasticity floor | Prevents single global floor from suppressing ALL premium picks regardless of demand |
| Doubly-robust correction | At the logged arm, correct model estimate toward observed outcome (bounded IPS weight) |
| Quality gate with rollback | Never deploy a regressed model; system always has a known-good fallback |
| Separate bootstrap vs. online n_observations | Fresh properties don't prematurely override their backbone safety net |

---

## Next

See [06-FEEDBACK-LOOP.md](./06-FEEDBACK-LOOP.md) for how revenue manager actions and real booking outcomes feed back into continuous model improvement.
