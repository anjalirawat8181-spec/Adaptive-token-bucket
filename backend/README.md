# Adaptive GIS Traffic Shaping backend

## Paper-aligned controller

The adaptive controller uses the paper's Eq. 6 and Eq. 11 with an experimentally
calibrated idle service rate `N`, the process load signal, and system task count
`Ls`. Eq. 10 is `delta = Ls/(1+Ls)` for positive `Ls`, and `1` otherwise. Eq. 12
is applied without normalizing its weights: RateRank 1 uses `(alpha, beta) =
(1, 1)`, rank 2 `(0.5, 1)`, and rank 3 `(0, 0.8)`. The rate is clamped to
`MinTokenRate = 1000 / SingleTaskCostTime` and `MaxTokenRate = worker_count *
1000 / SingleTaskCostTime`.

`simple`, `general`, and `complex` use task costs of 5, 20, and 80 ms. Mixed
workloads seed an EWMA (`TASK_COST_EWMA_ALPHA = 0.2`) with the workload's mean
nominal duration and update it from completed processing times. The controller
recomputes its rate bounds from that estimate. `ADAPTIVE_INITIAL_RATE_MODE =
"minimum"` starts each adaptive trial at its current minimum rate.
`calibrate_idle_service_rate(task_cost_ms)` measures a
40-task batch on an eight-worker pool and caches completions per second for
the life of the process. Set `IDLE_SERVICE_RATE_N_OVERRIDE` or pass
`idle_service_rate_n_override` to use a measured external calibration. Each
summary records the `N` value used.

The HMM uses the Eq. 5 emission matrix in its published orientation (columns
sum to one). It retains up to `HMM_WINDOW = 20` observations, runs Viterbi in
log space, and predicts the next RateRank from the transition row of the last
decoded state. Returned state probabilities are the normalized forward belief
over the observation window.

The `Ls` signal is active tasks + executor-queued tasks + released arrival
backlog + the request currently waiting for admission. The final `+1` is the
request being admitted. `mean_tasks` remains in diagnostics as a backwards
compatible alias for `ls_tasks_in_system`; it is no longer divided by worker
count.

## Load monitoring and contention simulation

`LOAD_SCOPE` defaults to `"process"`. In process scope, CPU is the benchmark
process CPU percentage divided by logical CPU count; memory is its RSS divided
by `SERVICE_MEMORY_BUDGET_BYTES` (default 1 GiB). Both are clamped to `[0, 1]`.
`"host"` scope is available for comparison. Host CPU and memory remain in
diagnostics in either scope and do not affect the default process-scoped load.
Resource-link utilization is active workers / configured workers.

CPU readings are nonblocking; the first reading is unavailable until a valid
interval has elapsed. Failed or unsupported indicators remain unavailable.
When an indicator is unavailable, `RENORMALIZE_UNAVAILABLE_INDICATORS = True`
renormalizes weights over available indicators. If none are available, the
controller update is skipped and the reason is recorded.

`CONTENTION_MODEL = True` simulates processor sharing in `_process_task`, using
`EFFECTIVE_PARALLELISM = 4.0` and `CONTENTION_SLICE_S = 0.002`. This is a local
contention simulation, not a real GIS workload. The parallelism value comes
from the paper's four-core/eight-thread test machine description and was not
tuned to favor either algorithm. Disable it with the run request to restore
plain duration sleeps. `BUCKET_CAPACITY` remains 8; the paper does not study
bucket capacity (Limitation 2).

## Benchmark protocol

Each paired trial uses the same seeded tasks and same zero-offset burst
schedule for both algorithms. The worker pool has eight workers. Task times
use `time.perf_counter()` and are decomposed into scheduler delay, controller
time, token admission wait, executor wait, and processing. End-to-end latency
starts at actual arrival and ends at completion. p90 and p95 use nearest-rank
percentiles.

Classical rate modes are `paper_preset`, `measured`, and `manual`. Presets are
200/100/50 tokens/s for simple/general/complex and 150 for mixed/dynamic.
Automatic selection uses a cached measured rate when one exists and otherwise
uses the paper preset. `POST /api/experiments/optimal-rate` sweeps candidate
rates over requested concurrency levels and repetitions, selecting the lowest
mean latency. Results are cached in `experiments/results/optimal_rates.json`
and read through `GET /api/experiments/optimal-rate/{scenario}`. The candidate
sets match the paper for simple, general, and complex; mixed and dynamic use
the union of the simple and general sets.

The dynamic scenario runs 70 paired mixed-workload bursts. Concurrency follows
the periodic envelope stand-in documented below and is reported with per-step
mean latency, p90 latency, throughput, adaptive rate range, and clamp fractions.
Relative differences average `(classical - adaptive) / classical` for latency
and p90, and `(adaptive - classical) / classical` for throughput. `speedup`
scales the envelope period.

`POST /api/experiments/sweep` produces mean and standard deviation for mean
latency, p90, and throughput over concurrency levels 1..200 at the requested
step. Requests estimated to exceed 15 minutes are rejected with a runtime
estimate and a suggestion to reduce repetitions or use a larger step.

## Deviations from the paper

- **Unavailable indicators:** weights are renormalized across available
  indicators; the paper does not specify a missing-indicator rule.
- **Load scope:** process CPU and RSS are used by default as a prototype proxy
  for the GIS server process. Set `LOAD_SCOPE = "host"` to use host readings.
- **Memory budget:** process RSS is normalized by a configurable 1 GiB default
  budget because this prototype does not have the paper's fixed GIS service
  memory limit.
- **Contention simulation:** the slice-based processor-sharing model is a
  simulation, not GIS processing. Its parallelism setting is an explicit
  configuration value, not a fitted parameter.
- **Dynamic traffic envelope:** the paper's cited Boryło et al. Eq. 14 was not
  available in this project brief. The code uses the requested periodic
  sinusoidal envelope as a stand-in. `TODO(Eq. 14)`: replace it with the exact
  formula from Boryło et al., *Computer Communications* 225 (2024), 250–278.
- **Adaptive initial rate:** the paper does not specify it; this implementation
  starts at the scenario's current `MinTokenRate`.
- **Mixed-task cost:** EWMA cost is seeded from the generated workload's mean
  nominal duration and updated from observed processing times.
- **Experiment calibration:** `N` is measured locally with a fixed 40-task
  batch; a supplied override is available for reproducible external hardware
  calibration.
- **Bucket capacity:** capacity remains 8, as an explicit prototype setting;
  the paper does not evaluate capacity changes.

## API example

```json
{
  "scenario": "mixed",
  "concurrency": 50,
  "repetitions": 5,
  "comparison": "both",
  "classical_rate_mode": "paper_preset",
  "contention_model": true,
  "load_scope": "process"
}
```

The existing `POST /api/experiments/run` and task, summary, and diagnostic CSV
downloads remain available. Dynamic runs also provide `dynamic_steps.csv`.

## Tests and local run

From `backend/` on Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
```

Start the API from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Start the UI in another terminal from `frontend/` with `npm run dev -- --host=127.0.0.1`.

Trial summaries include completion counts, latency and throughput, worker and
process/host resource measurements, task cost, `N`, classical rate and mode,
rate history, and clamp counts. `rate_diagnostics.csv` contains each adaptive
evaluation, process and host load measurements, Viterbi probabilities, `Ls`,
EWMA task cost, `N`, current rate bounds, and the selected rate. These results
are measurements of this prototype and do not imply that adaptive traffic
shaping beats the tuned classical baseline.
