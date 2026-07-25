# Dynamic Pricing MAB - POC

A multi-armed-bandit (contextual bandit, Vowpal Wabbit CB_ADF) dynamic
pricing engine for hotel revenue management, designed to scale from a
single-hotel POC to a 100k+ property, multi-chain, multi-region fleet.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design
write-up (org hierarchy, market-cluster pooling, ensemble-blend model
architecture, confidence scoring, guardrails, scalability plan, and
high/low-level diagrams).

Picking this up on a different machine/AI tool to continue the work? See
[dump/](dump/) - a self-contained, model-agnostic requirements/design/
tasks spec (plus a focused plan for closing the one open accuracy gap)
written so it doesn't depend on any prior conversation history.

## What's here

| Package | Purpose |
|---|---|
| `config/` | YAML config: arm ladder, context schema, market clusters, guardrails, per-tenant org hierarchy |
| `db/` | SQLAlchemy models (Property, RoomType, RatePlan, Decision) + session |
| `bandit_engine/` | Config loader, reference-rate math, VW-based `PropertyModel`/`BackboneModel`/`EnsemblePolicy` |
| `bandit_engine/training/` | Reward-model-based offline pretraining + fleet bootstrap + backtest/regret evaluation |
| `guardrails/` | Rule-registry action masking + approval-routing logic |
| `context_generator/` | Synthetic fleet + historical data generator (ground-truth demand simulator included) |
| `feedback/` | Decision logging + delayed reward reconciliation |
| `publisher/` | Channel-publish abstraction (mock for POC, adapter stub for production) |
| `serving/` | FastAPI serving layer (API-first; dashboard never touches the DB directly) |
| `model_registry/` | Filesystem-based model listing/inspection |
| `monitoring/` | Fleet metrics (arm distribution, override rate, confidence, approval stats) for the dashboard's JSON `/metrics`, plus the Prometheus scrape config + Grafana provisioning/dashboard for `/metrics/prometheus` (see step 10) |
| `orchestration/pipelines/` | Bootstrap + nightly retrain scripts (POC substitute for Airflow) |
| `dashboard/` | Streamlit UI: Rate Calendar, Approval Queue, Monitoring, Properties, Scenario Simulator, Recommendations (on-demand daily/weekly/monthly, with context overrides) |
| `Dockerfile.trainer` / `.api` / `.dashboard` / `.prometheus` / `.grafana`, `podman-compose.yml` | Docker/Podman Compose + Dockerfiles for `bootstrap`, `api`, `dashboard`, `prometheus`, `grafana` (kept at the project root - see note in step 9) |
| `tests/` | pytest suite |

## Prerequisites

- Python 3.11+ (this POC was built/verified against 3.13)
- Vowpal Wabbit's `vowpalwabbit` Python package (installed via `requirements.txt`)
- (Optional, for containerized run) Podman or Docker + compose. Podman itself
  does **not** bundle a compose provider - install one separately:
  `python -m pip install podman-compose` (cross-platform, what these docs
  assume) or Docker Desktop's `docker compose` if you have that instead.
  After installing, a **new** terminal session is needed to pick up the
  updated PATH (e.g. `podman-compose: command not found` in an
  already-open shell just means it was opened before the install).

## 1. Setup

```powershell
cd dynamic-pricing-MAB
python -m pip install -r requirements.txt
```

> **Windows note**: if `pip` resolves to a non-Python `pip.bat` on your
> PATH, use `python -m pip install -r requirements.txt` explicitly (as
> above) rather than a bare `pip install`.

## 2. Generate synthetic fleet + historical data

Creates 12 properties (2 chains x 6 properties each, across multiple
brands/regions) and 365 days of historical pricing decisions per
property/room-type/rate-plan, simulated against a ground-truth demand
model:

```powershell
python -m context_generator.multi_chain_synthetic_data
```

This is idempotent for properties (skips existing rows) but **appends**
Decision rows on every run - delete `data/pricing.db` first if you want a
clean regeneration.

## 3. Bootstrap-train the bandit models

Fits a reward-model-based pretraining set from historical data and trains
one `BackboneModel` per (cluster x tenant) plus one `PropertyModel` per
property (VW model artifacts land in `model_registry/artifacts/`):

```powershell
python -m bandit_engine.training.train
```

Or run data-gen + training together:

```powershell
python -m orchestration.pipelines.run_bootstrap
```

## 4. (Optional) Backtest a trained property against baseline

```powershell
python -c "from bandit_engine.training.offline_eval import run_backtest; print(run_backtest('marriott_courtyard_nyc_01', n_rounds=150))"
```

Or gate a set of properties with a statistical acceptance check:

```powershell
python -c "from bandit_engine.training.offline_eval import run_backtest_suite; from db.session import get_session; from db.models import Property; s=get_session(); ids=[p.property_id for p in s.query(Property).all()]; s.close(); r=run_backtest_suite(ids, n_rounds=150); print(r.n_wins, r.mean_reward_diff, r.ci_low, r.ci_high, r.reliably_beats_baseline)"
```

Compares the trained bandit's expected reward (evaluated greedily, i.e.
how it would actually be served) vs. the static baseline vs. the
(oracle-only) optimal policy, using the ground-truth demand model purely
as an evaluation oracle - never exposed to the bandit itself. See
[docs/ARCHITECTURE.md - Reliability plan](docs/ARCHITECTURE.md#reliability-plan---what-was-tried-what-actually-worked)
for the full history of what was tried and the current honestly-measured
result (large improvement, not yet a reliable win - documented, not hidden).

## 5. Run the serving API

```powershell
python -m uvicorn serving.api:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI docs at `http://127.0.0.1:8000/docs`. Key endpoints:
`GET /properties`, `POST /score`, `POST /simulate` (dry-run scenario
scoring), `POST /recommendations` (daily/weekly/monthly on-demand preview
across a date range, optional `context_overrides`), `GET /rate-calendar`,
`GET /approval-queue`, `POST
/approval-queue/{id}/approve|reject|override`, `GET /metrics`,
`GET /metrics/prometheus` (see step 10).

## 6. Run the dashboard

In a second terminal (with the API from step 5 still running):

```powershell
$env:API_BASE_URL = "http://127.0.0.1:8000"
python -m streamlit run dashboard/app.py
```

Opens at `http://localhost:8501` with 6 tabs: Rate Calendar, Approval
Queue, Monitoring, Properties, Scenario Simulator, Recommendations
(on-demand daily/weekly/monthly recommendations with optional context
overrides, then per-day approve/modify/reject).

## 7. Nightly retrain (simulated)

Reconciles delayed true rewards for decisions whose stay date has passed,
then retrains backbones on the freshened data:

```powershell
python -m orchestration.pipelines.run_nightly
```

## 8. Run tests

```powershell
python -m pytest tests/ -q
```

## 9. Containerized run (Podman/Docker)

### If you have Docker Desktop

`docker compose` doesn't have the bug described below - the one-command
path works:

```powershell
docker compose -f podman-compose.yml up --build
```

### If you have Podman (no Docker Desktop)

**`podman-compose` 1.6.0 (the latest release on PyPI as of writing) cannot
build this stack via `up --build`** - it has a bug where it ignores any
custom `dockerfile:` value entirely (confirmed: a plain `podman build -f
Dockerfile.trainer -t x .` run by hand works fine; `podman-compose`/`podman
compose` fail identically even with the compose file, Dockerfiles, and
build context all in the same directory with no path nesting at all). This
is a limitation of that tool, not of Podman, the Dockerfiles, or this
project's setup - see the comment block at the top of
[podman-compose.yml](podman-compose.yml) for the full diagnosis.

The reliable path today is to build and run each service manually (each
`podman build` command below is the exact equivalent of what compose would
have run for that service):

```powershell
# one-time: create the named volume the services share
podman volume create pricing-data

# build all three images
podman build -f Dockerfile.trainer -t pricing-bootstrap .
podman build -f Dockerfile.api -t pricing-api .
podman build -f Dockerfile.dashboard -t pricing-dashboard .

# run bootstrap once (data-gen + training) and wait for it to finish
podman run --rm -v pricing-data:/app/data pricing-bootstrap

# start api and dashboard (each in its own terminal, or add -d to detach)
podman run --rm -p 8000:8000 -v pricing-data:/app/data pricing-api
podman run --rm -p 8501:8501 -e API_BASE_URL=http://host.containers.internal:8000 pricing-dashboard
```

`host.containers.internal` lets the dashboard container reach the API
container's published port without a shared compose network - if that
hostname doesn't resolve on your Podman setup, use the host machine's
actual IP instead, or put both containers on an explicit `podman network`.
(To check this path works, run
`podman exec pricing-dashboard python -c "import httpx; print(httpx.get('http://host.containers.internal:8000/properties', timeout=5).status_code)"`
- it should print `200`.)

#### If `http://localhost:8000` / `:8501` don't load from Windows (Podman machine on WSL)

Symptom: `podman ps` shows both containers `Up`, their own logs show no
errors, but `curl`/browser requests to `localhost` or `127.0.0.1` hang or
fail (`curl` error 52 "empty reply from server", or the connection just
resets). This is a **Podman-machine-on-WSL2 port-forwarding bug**, not a
problem with the containers or this project: `netstat -ano | findstr :8000`
will typically show the port only `LISTENING` on `[::1]` (IPv6 loopback)
via a `wslrelay.exe` process, and that relay can silently fail to proxy
real HTTP traffic even though the raw TCP handshake succeeds. Restarting
the Podman machine (`podman machine stop <name>` / `start <name>`) does
**not** reliably fix this on some setups.

**Confirmed reliable workaround**: bypass the Windows-loopback relay
entirely and hit the Podman machine's own WSL IP directly:

```powershell
# find your podman machine's WSL distro name
wsl -l -v
# e.g. "podman-<your-machine-name>" - then get its IP:
wsl -d podman-<your-machine-name> -- ip -4 -o addr show
# use the eth0 inet address shown, e.g. 192.168.187.13
```

Then use `http://<that-ip>:8000` and `http://<that-ip>:8501` instead of
`localhost`. This IP is assigned by Windows' WSL virtual switch and can
change across reboots - re-run the command above if it stops responding
after a restart. This does **not** affect container-to-container traffic
(`host.containers.internal`, used by the dashboard to reach the API) -
that path works independently and was verified separately above.

If a future `podman-compose` release fixes the `dockerfile:` bug, the
original one-command form should work unchanged:

```powershell
podman-compose -f podman-compose.yml up --build
```

## 10. Monitoring with Prometheus + Grafana

`serving/api.py` exposes Prometheus-format metrics at `GET /metrics/prometheus`
(HTTP request rate/latency via `prometheus-fastapi-instrumentator`, plus
business metrics: `pricing_decisions_total`, `pricing_confidence_score`,
`pricing_approval_actions_total`, `pricing_publisher_calls_total`) - this is
separate from the JSON `GET /metrics` endpoint the Streamlit Monitoring tab
uses. To actually view these in Grafana, build and run two more containers
(same manual-podman-run pattern as step 9, for the same reason - custom
`dockerfile:` names aren't honored by `podman-compose` 1.6.0):

```powershell
podman build -f Dockerfile.prometheus -t pricing-prometheus .
podman build -f Dockerfile.grafana -t pricing-grafana .

# api (step 9) must already be running before prometheus starts scraping it
podman run --rm -p 9090:9090 pricing-prometheus
podman run --rm -p 3000:3000 pricing-grafana
```

- **Prometheus UI**: `http://127.0.0.1:9090` - check Status > Targets; the
  `pricing-api` job should show `host.containers.internal:8000` as `UP`
  (the `api:8000` target listed alongside it is only for the compose path
  below and will correctly show `DOWN` here - see
  [monitoring/prometheus.yml](monitoring/prometheus.yml)).
- **Grafana UI**: `http://127.0.0.1:3000` - login `admin` / `admin`
  (pre-set via `GF_SECURITY_ADMIN_PASSWORD` in the podman-compose version;
  for the manual `podman run` command above, add
  `-e GF_SECURITY_ADMIN_PASSWORD=admin` or just use the default `admin`/`admin`
  and set a new password when prompted). The Prometheus datasource and a
  **"Dynamic Pricing MAB - Overview"** dashboard (request rate/latency,
  decisions by arm/status, average confidence, approval actions, publisher
  calls) are auto-provisioned from [monitoring/grafana/](monitoring/grafana/)
  - nothing to click through manually; open it from Grafana's Dashboards list.
- Hit a few API endpoints (or use the dashboard/Scenario Simulator) and wait
  ~15-30s for a scrape cycle to see the panels populate.
- Same Windows/Podman networking bug as step 9 applies to reaching these
  UIs from a browser (`localhost:9090`/`:3000` may hang) - use the WSL VM IP
  workaround described above if that happens.
- If you're using `docker compose`/a fixed `podman-compose` instead of the
  manual commands above, edit `monitoring/grafana/provisioning/datasources/datasource.yml`'s
  `url` to `http://prometheus:9090` first (the manual path's
  `host.containers.internal` addressing doesn't apply on a compose network).

## Known POC limitations (documented honestly, not hidden)

- Historical logs are near-zero-exploration by design (mirrors real RM
  systems, plus a small full-ladder pilot-test fraction - `PILOT_EXPLORATION_PROB`
  in `context_generator/multi_chain_synthetic_data.py`, currently 0.15); the
  reward model used for offline pretraining is a gradient-boosted
  `XGBClassifier` with a native `monotone_constraints` on `offset_pct`, plus
  an explicit `PREMIUM_ELASTICITY_FLOOR` safety net (the native constraint
  alone only guarantees direction, not minimum decline rate) and distance-
  based shrinkage - a production system should additionally use proper full
  doubly-robust off-policy correction, not the single-arm approximation
  used here.
- The bootstrap-trained policy has been substantially improved (see
  [docs/ARCHITECTURE.md Reliability plan](docs/ARCHITECTURE.md#reliability-plan---what-was-tried-what-actually-worked) for the full
  before/after history) - the catastrophic overpricing failure mode is
  fixed (twice - once for the original linear model, again after a GBM
  switch reintroduced a similar regression that a premium elasticity floor
  then fixed), but it does **not** yet reliably beat the static baseline in
  `run_backtest_suite` (mean gap narrowed to -112.8 per 150 rounds across
  all 12 properties, 3/12 properties beating baseline, still not positive)
  - flagged as an open tuning item, not swept under the rug. Empirically
  confirmed that more *online* learning rounds alone do NOT close this gap
  under greedy serving (loss grows linearly with rounds, never shrinks) -
  the fix has to happen in the bootstrap/reward-model layer, not by
  waiting for more real interaction data to accumulate.
- Data residency / regional model hosting, and the comp-set-graph-based
  data-driven clustering upgrade, are designed and documented (see
  ARCHITECTURE.md) but not implemented in this POC's code - the domain
  tier clusters in `config/clusters.yaml` are used as-is.
