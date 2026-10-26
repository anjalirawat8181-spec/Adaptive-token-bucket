import csv
import json
import math
import queue
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, stdev
from types import MappingProxyType

from algorithms.token_bucket import TokenBucket
from algorithms.adaptive_token_bucket import AdaptiveRateController
from algorithms.load_calculator import calculate_load, load_rank
from monitoring.system_monitor import (
    LOAD_SCOPE,
    SERVICE_MEMORY_BUDGET_BYTES,
    SystemMonitor,
)


TASK_DURATIONS = {
    "simple": 5,
    "general": 20,
    "complex": 80,
}

SCENARIOS = {
    "simple": ["simple"],
    "general": ["general"],
    "complex": ["complex"],
    "mixed": ["simple", "general", "complex"],
    "dynamic": ["simple", "general", "complex"],
}
PAPER_CLASSICAL_RATE_PRESETS = {
    "simple": 200.0,
    "general": 100.0,
    "complex": 50.0,
    "mixed": 150.0,
    "dynamic": 150.0,
}
PAPER_CLASSICAL_RATE_CANDIDATES = {
    "simple": (50, 75, 100, 125, 150, 200),
    "general": (50, 100, 200, 300, 400, 500),
    "complex": (25, 50, 100, 200, 300, 400),
}
CLASSICAL_RATE_CACHE_PATH = (
    Path(__file__).resolve().parent / "results" / "optimal_rates.json"
)

MAX_WORKERS = 8
BUCKET_CAPACITY = 8
INITIAL_RATE = 50.0
TASK_COST_EWMA_ALPHA = 0.2
ADAPTIVE_INITIAL_RATE_MODE = "minimum"
CONTENTION_MODEL = True
EFFECTIVE_PARALLELISM = 4.0
CONTENTION_SLICE_S = 0.002
DAILY_ENVELOPE_C_MIN = 20
DAILY_ENVELOPE_C_MAX = 200
DAILY_ENVELOPE_PERIOD = 18.0
DAILY_ENVELOPE_STEPS = 70
IDLE_SERVICE_RATE_N_OVERRIDE = None
_IDLE_SERVICE_RATE_CACHE = {}
TASK_FIELDS = [
    "task_id",
    "task_type",
    "duration_ms",
    "submitted_s",
    "admitted_s",
    "started_s",
    "completed_s",
    "admission_delay_ms",
    "queue_wait_ms",
    "latency_ms",
    "processing_ms",
    "status",
    "error",
    "scenario",
    "algorithm",
    "concurrency",
    "trial",
    "workload_seed",
    "workload_id",
    "scheduled_arrival_offset_s",
    "scheduled_arrival_s",
    "actual_arrival_s",
    "external_arrival_to_submission_ms",
    "token_requested_s",
    "controller_update_ms",
    "token_admission_wait_ms",
]
SUMMARY_FIELDS = [
    "scenario",
    "algorithm",
    "concurrency",
    "trial",
    "completed_tasks",
    "failed_tasks",
    "timed_out_tasks",
    "elapsed_s",
    "average_latency_ms",
    "p95_latency_ms",
    "p90_latency_ms",
    "throughput_tasks_per_s",
    "average_cpu_utilization",
    "average_memory_utilization",
    "average_worker_utilization",
    "initial_token_rate",
    "final_token_rate",
    "rate_updates",
    "workload_seed",
    "workload_id",
    "algorithm_order",
    "total_tasks",
    "worker_count",
    "bucket_capacity",
    "adaptive_reference_task_cost_ms",
    "average_external_arrival_to_submission_ms",
    "average_arrival_to_admission_ms",
    "average_controller_update_ms",
    "average_token_admission_wait_ms",
    "average_executor_queue_wait_ms",
    "average_processing_ms",
    "minimum_observed_rate",
    "maximum_observed_rate",
    "average_observed_rate",
    "minimum_rate_clamps",
    "maximum_rate_clamps",
    "controller_evaluations",
    "rate_changes_per_s",
    "average_rate_change_magnitude",
    "time_at_minimum_rate_s",
    "time_at_maximum_rate_s",
    "time_below_initial_rate_s",
    "time_at_or_above_initial_rate_s",
    "idle_service_rate_n",
    "classical_token_rate",
    "load_scope",
    "average_host_cpu_utilization",
    "average_host_memory_utilization",
    "service_memory_budget_bytes",
    "contention_model",
    "effective_parallelism",
    "rate_mode",
    "dynamic_step",
]
RATE_DIAGNOSTIC_FIELDS = [
    "scenario",
    "algorithm",
    "trial",
    "task_id",
    "elapsed_s",
    "monitor_sample_age_s",
    "cpu_utilization",
    "memory_utilization",
    "host_cpu_utilization",
    "host_memory_utilization",
    "worker_utilization",
    "load",
    "load_rank",
    "load_indicator_states",
    "load_weights",
    "predicted_rate_rank",
    "state_probabilities",
    "rate_before",
    "proposed_rate",
    "applied_rate",
    "minimum_rate",
    "maximum_rate",
    "active_workers",
    "idle_worker_slots",
    "load_scope",
    "estimated_task_cost_ms",
    "idle_service_rate_n",
    "executor_queued_tasks",
    "arrival_backlog_tasks",
    "outstanding_tasks",
    "ls_tasks_in_system",
    "mean_tasks",
    "service_capacity_tasks_per_s",
    "remaining_capacity_tasks_per_s",
    "alpha",
    "beta",
    "delta",
    "controller_updated",
    "rate_changed",
    "rate_delta",
    "clamp_reason",
    "skip_reason",
]
DYNAMIC_STEP_FIELDS = [
    "step",
    "concurrency",
    "algorithm",
    "mean_latency_ms",
    "p90_latency_ms",
    "throughput_tasks_per_s",
    "classical_rate",
    "adaptive_rate_min",
    "adaptive_rate_mean",
    "adaptive_rate_max",
    "adaptive_min_clamp_fraction",
    "adaptive_max_clamp_fraction",
]


class WorkerTracker:
    def __init__(self, total_workers):
        if not isinstance(total_workers, int) or total_workers < 1:
            raise ValueError("total_workers must be a positive integer")
        self.total_workers = total_workers
        self._active = 0
        self._queued = 0
        self._active_since = None
        self._active_worker_seconds = 0.0
        self._lock = threading.Lock()

    def task_queued(self):
        with self._lock:
            self._queued += 1

    def task_started(self):
        with self._lock:
            if self._queued <= 0:
                raise RuntimeError("Started task was not marked as queued")
            now = time.perf_counter()
            self._record_active_time(now)
            self._queued -= 1
            self._active += 1
            self._active_since = now

    def task_finished(self):
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("Finished task was not marked as active")
            now = time.perf_counter()
            self._record_active_time(now)
            self._active -= 1
            self._active_since = now if self._active else None

    def _record_active_time(self, now):
        if self._active_since is not None:
            self._active_worker_seconds += (
                now - self._active_since
            ) * self._active
        self._active_since = now

    def cancel_queued_task(self):
        with self._lock:
            if self._queued <= 0:
                raise RuntimeError("No queued task is available to cancel")
            self._queued -= 1

    def snapshot(self):
        with self._lock:
            active = self._active
            queued = self._queued
        return {
            "active_workers": active,
            "queued_tasks": queued,
            "available_worker_slots": max(
                self.total_workers - active - queued, 0
            ),
            "outstanding_tasks": active + queued,
            "worker_utilization": min(
                max(active / self.total_workers, 0.0),
                1.0,
            ),
        }

    def average_utilization(self, started_at, completed_at):
        elapsed = completed_at - started_at
        if elapsed <= 0:
            return None
        with self._lock:
            active_worker_seconds = self._active_worker_seconds
            if self._active_since is not None:
                active_worker_seconds += (
                    completed_at - self._active_since
                ) * self._active
        return min(
            max(
                active_worker_seconds / (self.total_workers * elapsed),
                0.0,
            ),
            1.0,
        )


def generate_workload(scenario_name, concurrency, seed=42):
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    if not 1 <= concurrency <= 200:
        raise ValueError("Concurrency must be between 1 and 200")

    rng = random.Random(seed)
    types = SCENARIOS[scenario_name]
    workload_id = f"{scenario_name}-{concurrency}-seed-{seed}"
    tasks = []

    scheduled_at_s = 0.0
    for task_id in range(1, concurrency + 1):
        task_type = rng.choice(types)

        delay_ms = 0
        scheduled_at_s += delay_ms / 1000.0

        tasks.append(MappingProxyType({
            "task_id": task_id,
            "scenario": scenario_name,
            "task_type": task_type,
            "duration_ms": TASK_DURATIONS[task_type],
            "scheduled_arrival_offset_s": scheduled_at_s,
            "workload_seed": seed,
            "workload_id": workload_id,
        }))

    return tuple(tasks)


def _failure_record(
    task, actual_arrival_at, submitted_at, completed_at,
    admitted_at=None, token_requested_at=None, error=None,
    status="failed",
):
    admission_delay = (completed_at - actual_arrival_at) * 1000
    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "duration_ms": task["duration_ms"],
        "workload_id": task["workload_id"],
        "scheduled_arrival_offset_s": task["scheduled_arrival_offset_s"],
        "scheduled_arrival_s": task["scheduled_arrival_s"],
        "actual_arrival_s": actual_arrival_at,
        "external_arrival_to_submission_ms": (
            submitted_at - actual_arrival_at
        ) * 1000,
        "submitted_s": submitted_at,
        "token_requested_s": token_requested_at,
        "controller_update_ms": (
            (token_requested_at - submitted_at) * 1000
            if token_requested_at is not None
            else None
        ),
        "admitted_s": admitted_at,
        "started_s": None,
        "completed_s": completed_at,
        "admission_delay_ms": admission_delay,
        "token_admission_wait_ms": (
            (completed_at - token_requested_at) * 1000
            if token_requested_at is not None
            else None
        ),
        "queue_wait_ms": None,
        "latency_ms": (completed_at - actual_arrival_at) * 1000,
        "processing_ms": None,
        "status": status,
        "error": error,
    }


def _process_task(
    task,
    actual_arrival_at,
    submitted_at,
    token_requested_at,
    admitted_at,
    tracker,
    contention_model=CONTENTION_MODEL,
):
    started_at = time.perf_counter()
    tracker.task_started()
    status = "success"
    error = None
    try:
        remaining_s = task["duration_ms"] / 1000.0
        if contention_model:
            while remaining_s > 1e-6:
                active = max(tracker.snapshot()["active_workers"], 1)
                share = min(1.0, EFFECTIVE_PARALLELISM / active)
                wall_slice = min(CONTENTION_SLICE_S, remaining_s / share)
                # Credit the time actually slept, not the time requested:
                # on Windows time.sleep(0.002) really sleeps ~15.6 ms.
                slice_started = time.perf_counter()
                time.sleep(wall_slice)
                slept_s = time.perf_counter() - slice_started
                remaining_s -= slept_s * share
        else:
            time.sleep(remaining_s)
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        completed_at = time.perf_counter()
        tracker.task_finished()

    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "duration_ms": task["duration_ms"],
        "workload_id": task["workload_id"],
        "scheduled_arrival_offset_s": task["scheduled_arrival_offset_s"],
        "scheduled_arrival_s": task["scheduled_arrival_s"],
        "actual_arrival_s": actual_arrival_at,
        "external_arrival_to_submission_ms": (
            submitted_at - actual_arrival_at
        ) * 1000,
        "submitted_s": submitted_at,
        "token_requested_s": token_requested_at,
        "controller_update_ms": (
            token_requested_at - submitted_at
        ) * 1000,
        "admitted_s": admitted_at,
        "started_s": started_at,
        "completed_s": completed_at,
        "admission_delay_ms": (admitted_at - actual_arrival_at) * 1000,
        "token_admission_wait_ms": (
            admitted_at - token_requested_at
        ) * 1000,
        "queue_wait_ms": (started_at - admitted_at) * 1000,
        "latency_ms": (completed_at - actual_arrival_at) * 1000,
        "processing_ms": (completed_at - started_at) * 1000,
        "status": status,
        "error": error,
    }


def _p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def daily_envelope_concurrency(step, speedup=1.0):
    # TODO(Eq. 14): replace this stand-in with Boryło et al., Computer
    # Communications 225 (2024), 250-278, once that formula is available.
    if not 0 <= step < DAILY_ENVELOPE_STEPS:
        raise ValueError("step is outside the daily envelope")
    if not math.isfinite(speedup) or speedup <= 0:
        raise ValueError("speedup must be positive and finite")
    period = DAILY_ENVELOPE_PERIOD / speedup
    value = DAILY_ENVELOPE_C_MIN + (
        DAILY_ENVELOPE_C_MAX - DAILY_ENVELOPE_C_MIN
    ) * 0.5 * (1 + math.sin(2 * math.pi * step / period - math.pi / 2))
    return round(value)


def calibrate_idle_service_rate(
    task_cost_ms,
    *,
    workers=MAX_WORKERS,
    batch_size=40,
    override=IDLE_SERVICE_RATE_N_OVERRIDE,
    contention_model=CONTENTION_MODEL,
):
    if override is not None:
        if not math.isfinite(override) or override <= 0:
            raise ValueError("idle service rate override must be positive")
        return float(override)
    if task_cost_ms <= 0 or workers < 1 or batch_size < workers:
        raise ValueError("invalid idle service calibration configuration")
    key = (round(float(task_cost_ms), 6), workers, batch_size, contention_model)
    if key in _IDLE_SERVICE_RATE_CACHE:
        return _IDLE_SERVICE_RATE_CACHE[key]

    tracker = WorkerTracker(workers)

    def run_calibration_task():
        tracker.task_queued()
        tracker.task_started()
        try:
            remaining_s = task_cost_ms / 1000.0
            if contention_model:
                while remaining_s > 1e-6:
                    active = max(tracker.snapshot()["active_workers"], 1)
                    share = min(1.0, EFFECTIVE_PARALLELISM / active)
                    wall_slice = min(CONTENTION_SLICE_S, remaining_s / share)
                    # Credit the time actually slept, not the time requested:
                    # on Windows time.sleep(0.002) really sleeps ~15.6 ms.
                    slice_started = time.perf_counter()
                    time.sleep(wall_slice)
                    slept_s = time.perf_counter() - slice_started
                    remaining_s -= slept_s * share
            else:
                time.sleep(remaining_s)
        finally:
            tracker.task_finished()

    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_calibration_task) for _ in range(batch_size)]
        for future in as_completed(futures):
            future.result()
    elapsed = time.perf_counter() - started_at
    service_rate = batch_size / elapsed
    _IDLE_SERVICE_RATE_CACHE[key] = service_rate
    return service_rate


def _rate_history_metrics(events, elapsed_s, initial_rate, min_rate, max_rate):
    history = sorted(
        (
            event["elapsed_s"],
            event["applied_rate"],
            event.get("minimum_rate"),
            event.get("maximum_rate"),
        )
        for event in events
        if event["applied_rate"] is not None
    )
    observed_rates = [initial_rate] + [rate for _, rate, _, _ in history]
    current_rate = initial_rate
    previous_time = 0.0
    weighted_rate_seconds = 0.0
    time_at_minimum = 0.0
    time_at_maximum = 0.0
    time_below_initial = 0.0
    time_at_or_above_initial = 0.0

    for event_time, next_rate, next_minimum, next_maximum in history:
        event_time = min(max(event_time, previous_time), elapsed_s)
        duration = event_time - previous_time
        weighted_rate_seconds += current_rate * duration
        if min_rate is not None and math.isclose(
            current_rate, min_rate, rel_tol=1e-9, abs_tol=1e-9
        ):
            time_at_minimum += duration
        if max_rate is not None and math.isclose(
            current_rate, max_rate, rel_tol=1e-9, abs_tol=1e-9
        ):
            time_at_maximum += duration
        if current_rate < initial_rate:
            time_below_initial += duration
        else:
            time_at_or_above_initial += duration
        previous_time = event_time
        current_rate = next_rate
        if next_minimum is not None:
            min_rate = next_minimum
        if next_maximum is not None:
            max_rate = next_maximum

    duration = max(elapsed_s - previous_time, 0.0)
    weighted_rate_seconds += current_rate * duration
    if min_rate is not None and math.isclose(
        current_rate, min_rate, rel_tol=1e-9, abs_tol=1e-9
    ):
        time_at_minimum += duration
    if max_rate is not None and math.isclose(
        current_rate, max_rate, rel_tol=1e-9, abs_tol=1e-9
    ):
        time_at_maximum += duration
    if current_rate < initial_rate:
        time_below_initial += duration
    else:
        time_at_or_above_initial += duration

    return {
        "minimum_observed_rate": min(observed_rates),
        "maximum_observed_rate": max(observed_rates),
        "average_observed_rate": (
            weighted_rate_seconds / elapsed_s if elapsed_s > 0 else None
        ),
        "minimum_rate_clamps": sum(
            event["clamp_reason"] == "minimum" for event in events
        ),
        "maximum_rate_clamps": sum(
            event["clamp_reason"] == "maximum" for event in events
        ),
        "time_at_minimum_rate_s": (
            time_at_minimum if min_rate is not None else None
        ),
        "time_at_maximum_rate_s": (
            time_at_maximum if max_rate is not None else None
        ),
        "time_below_initial_rate_s": time_below_initial,
        "time_at_or_above_initial_rate_s": time_at_or_above_initial,
    }


def run_trial(
    scenario,
    concurrency,
    algorithm,
    trial_number,
    sampling_interval_s=0.05,
    workload=None,
    workload_seed=None,
    algorithm_order=None,
    classical_rate=None,
    contention_model=CONTENTION_MODEL,
    idle_service_rate_override=IDLE_SERVICE_RATE_N_OVERRIDE,
    rate_mode=None,
    load_scope=LOAD_SCOPE,
):
    if workload_seed is None:
        workload_seed = 42 + trial_number
    if workload is None:
        workload = generate_workload(scenario, concurrency, seed=workload_seed)

    nominal_cost_ms = mean(task["duration_ms"] for task in workload)
    if scenario in {"simple", "general", "complex"}:
        nominal_cost_ms = TASK_DURATIONS[scenario]
    calibration_cost_ms = (
        nominal_cost_ms
        if scenario in {"simple", "general", "complex"}
        else mean(TASK_DURATIONS.values())
    )
    idle_service_rate_n = calibrate_idle_service_rate(
        calibration_cost_ms,
        override=idle_service_rate_override,
        contention_model=contention_model,
    )
    if algorithm == "adaptive":
        if ADAPTIVE_INITIAL_RATE_MODE != "minimum":
            raise ValueError("Unsupported adaptive initial-rate mode")
        initial_rate = 1000.0 / nominal_cost_ms
    else:
        initial_rate = (
            classical_rate if classical_rate is not None else INITIAL_RATE
        )
    bucket = TokenBucket(
        rate=initial_rate,
        capacity=BUCKET_CAPACITY,
    )

    controller = None
    if algorithm == "adaptive":
        controller = AdaptiveRateController(
            initial_rate=initial_rate,
            max_threads=MAX_WORKERS,
            task_cost_ms=nominal_cost_ms,
            service_rate_n=idle_service_rate_n,
        )
    elif algorithm != "classical":
        raise ValueError("Algorithm must be classical or adaptive")

    tracker = WorkerTracker(MAX_WORKERS)
    records = []
    futures = {}
    rate_updates = 0
    rate_diagnostics = []

    with SystemMonitor(
        active_workers=lambda: tracker.snapshot()["active_workers"],
        total_workers=MAX_WORKERS,
        sampling_interval_s=sampling_interval_s,
        load_scope=load_scope,
    ) as monitor:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            trial_start = time.perf_counter()
            schedule = []
            for task in workload:
                scheduled_task = dict(task)
                scheduled_task["scheduled_arrival_s"] = (
                    trial_start + task["scheduled_arrival_offset_s"]
                )
                schedule.append(scheduled_task)

            arrivals = queue.Queue(maxsize=max(1, len(schedule)))
            scheduler_errors = []
            stop_scheduler = threading.Event()

            def release_arrivals():
                try:
                    for scheduled_task in schedule:
                        if stop_scheduler.is_set():
                            return
                        delay = scheduled_task["scheduled_arrival_s"] - time.perf_counter()
                        if delay > 0:
                            stop_scheduler.wait(delay)
                        if stop_scheduler.is_set():
                            return
                        while not stop_scheduler.is_set():
                            try:
                                arrivals.put(
                                    (scheduled_task, time.perf_counter()),
                                    timeout=0.05,
                                )
                                break
                            except queue.Full:
                                continue
                except BaseException as exc:
                    scheduler_errors.append(exc)

            scheduler = threading.Thread(
                target=release_arrivals,
                name="benchmark-arrival-scheduler",
                daemon=True,
            )
            scheduler.start()
            task_cost_state = [nominal_cost_ms]
            task_cost_lock = threading.Lock()
            try:
                for _ in schedule:
                    if scheduler_errors:
                        raise RuntimeError(
                            "Arrival scheduler failed"
                        ) from scheduler_errors[0]
                    while True:
                        if scheduler_errors:
                            raise RuntimeError(
                                "Arrival scheduler failed"
                            ) from scheduler_errors[0]
                        try:
                            task, actual_arrival_at = arrivals.get(timeout=0.1)
                            break
                        except queue.Empty:
                            continue
                    submitted_at = time.perf_counter()

                    if controller is not None:
                        metrics = monitor.snapshot()
                        worker_state = tracker.snapshot()
                        arrival_backlog = arrivals.qsize()
                        with task_cost_lock:
                            estimated_task_cost_ms = task_cost_state[0]
                        controller.set_task_cost_ms(estimated_task_cost_ms)
                        bucket.set_rate(controller.rate)
                        ls_tasks_in_system = (
                            worker_state["outstanding_tasks"]
                            + arrival_backlog
                            + 1
                        )
                        metrics["resource_usage"] = worker_state[
                            "worker_utilization"
                        ]
                        load_result = calculate_load(
                            cpu=metrics["cpu"],
                            memory=metrics["memory"],
                            resources=metrics["resource_usage"],
                        )
                        rate_before = controller.rate
                        update = None
                        skip_reason = None
                        if metrics["sample_age_s"] > 3 * sampling_interval_s:
                            skip_reason = "monitoring snapshot stale"
                        elif load_result["load"] is None:
                            skip_reason = "no valid load indicators"
                        else:
                            update = controller.update(
                                load=load_result["load"],
                                load_rank=load_rank(load_result["load"]),
                                ls_tasks_in_system=ls_tasks_in_system,
                                idle_capacity=(
                                    worker_state["available_worker_slots"]
                                ),
                            )
                            bucket.set_rate(update["token_rate"])
                            changed = not math.isclose(
                                rate_before,
                                update["token_rate"],
                                rel_tol=1e-12,
                                abs_tol=1e-12,
                            )
                            rate_updates += int(changed)
                            if update["skip_reason"]:
                                skip_reason = update["skip_reason"]

                        rate_diagnostics.append({
                            "scenario": scenario,
                            "algorithm": algorithm,
                            "trial": trial_number,
                            "task_id": task["task_id"],
                            "load_scope": load_scope,
                            "elapsed_s": time.perf_counter() - trial_start,
                            "monitor_sample_age_s": metrics["sample_age_s"],
                            "cpu_utilization": metrics["cpu"],
                            "memory_utilization": metrics["memory"],
                            "host_cpu_utilization": metrics[
                                "host_cpu_utilization"
                            ],
                            "host_memory_utilization": metrics[
                                "host_memory_utilization"
                            ],
                            "worker_utilization": worker_state[
                                "worker_utilization"
                            ],
                            "load": load_result["load"],
                            "load_rank": (
                                load_rank(load_result["load"])
                                if load_result["load"] is not None
                                else None
                            ),
                            "load_indicator_states": json.dumps(
                                load_result["states"]
                            ),
                            "load_weights": json.dumps(
                                load_result["weights"]
                            ),
                            "predicted_rate_rank": (
                                update["rate_rank"] if update else None
                            ),
                            "state_probabilities": (
                                json.dumps(update["state_probabilities"])
                                if update
                                and update["state_probabilities"] is not None
                                else None
                            ),
                            "rate_before": rate_before,
                            "proposed_rate": (
                                update["proposed_rate"] if update else rate_before
                            ),
                            "applied_rate": bucket.rate,
                            "minimum_rate": controller.min_rate,
                            "maximum_rate": controller.max_rate,
                            "active_workers": worker_state["active_workers"],
                            "idle_worker_slots": worker_state[
                                "available_worker_slots"
                            ],
                            "executor_queued_tasks": worker_state["queued_tasks"],
                            "arrival_backlog_tasks": arrival_backlog,
                            "outstanding_tasks": worker_state[
                                "outstanding_tasks"
                            ],
                            "ls_tasks_in_system": ls_tasks_in_system,
                            "mean_tasks": ls_tasks_in_system,
                            "estimated_task_cost_ms": estimated_task_cost_ms,
                            "idle_service_rate_n": idle_service_rate_n,
                            "service_capacity_tasks_per_s": (
                                update["service_capacity"] if update else None
                            ),
                            "remaining_capacity_tasks_per_s": (
                                update["remaining_capacity"] if update else None
                            ),
                            "alpha": update["alpha"] if update else None,
                            "beta": update["beta"] if update else None,
                            "delta": update["delta"] if update else None,
                            "controller_updated": bool(
                                update and update["updated"]
                            ),
                            "rate_changed": bool(
                                update
                                and not math.isclose(
                                    rate_before,
                                    update["token_rate"],
                                    rel_tol=1e-12,
                                    abs_tol=1e-12,
                                )
                            ),
                            "rate_delta": abs(
                                bucket.rate - rate_before
                            ),
                            "clamp_reason": (
                                update["clamp_reason"] if update else None
                            ),
                            "skip_reason": skip_reason,
                        })

                    token_requested_at = time.perf_counter()

                    if not bucket.acquire(timeout=30):
                        failed_at = time.perf_counter()
                        records.append(_failure_record(
                            task,
                            actual_arrival_at,
                            submitted_at,
                            failed_at,
                            token_requested_at=token_requested_at,
                            error="Token admission timed out",
                            status="timed_out",
                        ))
                        continue

                    admitted_at = time.perf_counter()
                    tracker.task_queued()
                    try:
                        future = pool.submit(
                            _process_task,
                            task,
                            actual_arrival_at,
                            submitted_at,
                            token_requested_at,
                            admitted_at,
                            tracker,
                            contention_model,
                        )
                    except Exception as exc:
                        tracker.cancel_queued_task()
                        records.append(_failure_record(
                            task,
                            actual_arrival_at,
                            submitted_at,
                            time.perf_counter(),
                            admitted_at=admitted_at,
                            token_requested_at=token_requested_at,
                            error=f"{type(exc).__name__}: {exc}",
                        ))
                        continue
                    futures[future] = (
                        task,
                        actual_arrival_at,
                        submitted_at,
                        token_requested_at,
                        admitted_at,
                    )
                    if controller is not None and scenario in {"mixed", "dynamic"}:
                        def observe_processing(done_future):
                            try:
                                processing_record = done_future.result()
                            except Exception:
                                return
                            if processing_record["processing_ms"] is None:
                                return
                            with task_cost_lock:
                                task_cost_state[0] = (
                                    TASK_COST_EWMA_ALPHA
                                    * processing_record["processing_ms"]
                                    + (1.0 - TASK_COST_EWMA_ALPHA)
                                    * task_cost_state[0]
                                )
                                updated_cost = task_cost_state[0]
                            controller.set_task_cost_ms(updated_cost)
                            bucket.set_rate(controller.rate)

                        future.add_done_callback(observe_processing)

                for future in as_completed(futures):
                    (
                        task,
                        actual_arrival_at,
                        submitted_at,
                        token_requested_at,
                        admitted_at,
                    ) = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = _failure_record(
                            task,
                            actual_arrival_at,
                            submitted_at,
                            time.perf_counter(),
                            admitted_at=admitted_at,
                            token_requested_at=token_requested_at,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    records.append(record)
            finally:
                stop_scheduler.set()
                scheduler.join()

        monitor.stop()
        trial_end = time.perf_counter()
        metric_averages = monitor.averages()

    elapsed = trial_end - trial_start
    if elapsed <= 0:
        raise RuntimeError("Benchmark wall-clock duration must be positive")

    for record in records:
        record.update({
            "scenario": scenario,
            "algorithm": algorithm,
            "concurrency": concurrency,
            "trial": trial_number,
            "workload_seed": workload_seed,
            "workload_id": f"{scenario}-{concurrency}-seed-{workload_seed}",
        })
    records.sort(key=lambda row: row["task_id"])

    successful_latencies = [
        row["latency_ms"]
        for row in records
        if row["status"] == "success"
    ]
    rate_history = _rate_history_metrics(
        rate_diagnostics,
        elapsed,
        initial_rate,
        1000.0 / nominal_cost_ms if controller else None,
        MAX_WORKERS * 1000.0 / nominal_cost_ms if controller else None,
    )
    completed = len(successful_latencies)
    summary = {
        "scenario": scenario,
        "algorithm": algorithm,
        "concurrency": concurrency,
        "trial": trial_number,
        "completed_tasks": completed,
        "failed_tasks": sum(row["status"] == "failed" for row in records),
        "timed_out_tasks": sum(
            row["status"] == "timed_out" for row in records
        ),
        "elapsed_s": elapsed,
        "average_latency_ms": (
            mean(successful_latencies) if successful_latencies else None
        ),
        "p95_latency_ms": _p95(successful_latencies),
        "p90_latency_ms": _percentile(successful_latencies, 0.90),
        "throughput_tasks_per_s": completed / elapsed,
        "average_cpu_utilization": metric_averages["cpu"],
        "average_memory_utilization": metric_averages["memory"],
        "average_worker_utilization": tracker.average_utilization(
            trial_start,
            trial_end,
        ),
        "initial_token_rate": initial_rate,
        "final_token_rate": bucket.rate,
        "rate_updates": rate_updates,
        "workload_seed": workload_seed,
        "workload_id": f"{scenario}-{concurrency}-seed-{workload_seed}",
        "algorithm_order": algorithm_order or algorithm,
        "total_tasks": concurrency,
        "worker_count": MAX_WORKERS,
        "bucket_capacity": BUCKET_CAPACITY,
        "adaptive_reference_task_cost_ms": nominal_cost_ms,
        "idle_service_rate_n": idle_service_rate_n,
        "classical_token_rate": (
            initial_rate if algorithm == "classical" else None
        ),
        "load_scope": load_scope,
        "average_host_cpu_utilization": metric_averages[
            "host_cpu_utilization"
        ],
        "average_host_memory_utilization": metric_averages[
            "host_memory_utilization"
        ],
        "service_memory_budget_bytes": SERVICE_MEMORY_BUDGET_BYTES,
        "contention_model": contention_model,
        "effective_parallelism": (
            EFFECTIVE_PARALLELISM if contention_model else None
        ),
        "rate_mode": rate_mode,
        "average_external_arrival_to_submission_ms": (
            mean(row["external_arrival_to_submission_ms"] for row in records)
            if records else None
        ),
        "average_arrival_to_admission_ms": (
            mean(row["admission_delay_ms"] for row in records)
            if records else None
        ),
        "average_controller_update_ms": (
            mean(row["controller_update_ms"] for row in records
                 if row["controller_update_ms"] is not None)
            if any(row["controller_update_ms"] is not None for row in records)
            else None
        ),
        "average_token_admission_wait_ms": (
            mean(row["token_admission_wait_ms"] for row in records
                 if row["token_admission_wait_ms"] is not None)
            if any(row["token_admission_wait_ms"] is not None for row in records)
            else None
        ),
        "average_executor_queue_wait_ms": (
            mean(row["queue_wait_ms"] for row in records
                 if row["queue_wait_ms"] is not None)
            if any(row["queue_wait_ms"] is not None for row in records)
            else None
        ),
        "average_processing_ms": (
            mean(row["processing_ms"] for row in records
                 if row["processing_ms"] is not None)
            if any(row["processing_ms"] is not None for row in records)
            else None
        ),
        **rate_history,
        "controller_evaluations": len(rate_diagnostics),
        "rate_changes_per_s": rate_updates / elapsed,
        "average_rate_change_magnitude": (
            mean(event["rate_delta"] for event in rate_diagnostics)
            if rate_diagnostics else 0.0
        ),
    }
    summary["rate_updates"] = rate_updates
    return records, summary, rate_diagnostics


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _candidate_rates_for_scenario(scenario):
    if scenario in PAPER_CLASSICAL_RATE_CANDIDATES:
        return PAPER_CLASSICAL_RATE_CANDIDATES[scenario]
    union = set(PAPER_CLASSICAL_RATE_CANDIDATES["simple"])
    union.update(PAPER_CLASSICAL_RATE_CANDIDATES["general"])
    return tuple(sorted(union))


def load_optimal_classical_rates(path=CLASSICAL_RATE_CACHE_PATH):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def find_optimal_classical_rate(
    scenario,
    candidate_rates=None,
    concurrency_levels=range(1, 201, 5),
    repetitions=20,
    cache_path=CLASSICAL_RATE_CACHE_PATH,
):
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    candidates = tuple(candidate_rates or _candidate_rates_for_scenario(scenario))
    levels = tuple(concurrency_levels)
    if not candidates or any(rate <= 0 for rate in candidates):
        raise ValueError("candidate_rates must contain positive rates")
    if not levels or any(not 1 <= level <= 200 for level in levels):
        raise ValueError("concurrency_levels must be between 1 and 200")
    if not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be between 1 and 20")

    results = []
    for rate in candidates:
        latencies = []
        throughputs = []
        for concurrency in levels:
            for trial in range(1, repetitions + 1):
                seed = 42 + trial
                workload = generate_workload(scenario, concurrency, seed)
                _, summary, _ = run_trial(
                    scenario,
                    concurrency,
                    "classical",
                    trial,
                    workload=workload,
                    workload_seed=seed,
                    classical_rate=float(rate),
                    rate_mode="measured",
                )
                if summary["average_latency_ms"] is not None:
                    latencies.append(summary["average_latency_ms"])
                throughputs.append(summary["throughput_tasks_per_s"])
        results.append({
            "rate": float(rate),
            "mean_latency_ms": mean(latencies) if latencies else None,
            "std_latency_ms": stdev(latencies) if len(latencies) > 1 else 0.0,
            "mean_throughput_tasks_per_s": (
                mean(throughputs) if throughputs else None
            ),
        })
    usable = [row for row in results if row["mean_latency_ms"] is not None]
    if not usable:
        raise RuntimeError("No classical candidate produced completed tasks")
    best = min(usable, key=lambda row: row["mean_latency_ms"])
    result = {
        "scenario": scenario,
        "rate": best["rate"],
        "candidate_rates": list(candidates),
        "concurrency_levels": list(levels),
        "repetitions": repetitions,
        "sweep": results,
    }
    cache_path = Path(cache_path)
    cache = load_optimal_classical_rates(cache_path)
    cache[scenario] = result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return result


def run_concurrency_sweep(
    scenario,
    concurrency_step=5,
    repetitions=20,
    comparison="both",
    output_dir=None,
    max_runtime_s=900,
):
    if scenario not in {"simple", "general", "complex", "mixed"}:
        raise ValueError("Concurrency sweep supports simple, general, complex, or mixed")
    if not 1 <= concurrency_step <= 200:
        raise ValueError("concurrency_step must be between 1 and 200")
    if not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be between 1 and 20")
    if comparison not in {"both", "classical", "adaptive"}:
        raise ValueError("Invalid comparison mode")
    levels = tuple(range(1, 201, concurrency_step))
    algorithms = ["classical", "adaptive"] if comparison == "both" else [comparison]
    nominal_ms = (
        TASK_DURATIONS[scenario]
        if scenario in TASK_DURATIONS
        else mean(TASK_DURATIONS.values())
    )
    expected_rate = PAPER_CLASSICAL_RATE_PRESETS[scenario]
    estimate_s = repetitions * len(levels) * len(algorithms) * sum(
        max(
            concurrency * nominal_ms / (EFFECTIVE_PARALLELISM * 1000.0),
            max(concurrency - BUCKET_CAPACITY, 0) / expected_rate,
        )
        for concurrency in levels
    )
    if estimate_s > max_runtime_s:
        raise ValueError(
            f"Estimated sweep runtime is {estimate_s / 60:.1f} minutes; "
            f"reduce repetitions or increase concurrency_step (limit: "
            f"{max_runtime_s / 60:.0f} minutes)."
        )

    summaries_by_point = {}
    for concurrency in levels:
        summaries_by_point[concurrency] = {algorithm: [] for algorithm in algorithms}
        for trial in range(1, repetitions + 1):
            workload_seed = 42 + trial
            workload = generate_workload(scenario, concurrency, workload_seed)
            order = algorithms if trial % 2 else list(reversed(algorithms))
            for algorithm in order:
                _, summary, _ = run_trial(
                    scenario,
                    concurrency,
                    algorithm,
                    trial,
                    workload=workload,
                    workload_seed=workload_seed,
                    classical_rate=expected_rate,
                    rate_mode="paper_preset",
                )
                summaries_by_point[concurrency][algorithm].append(summary)

    points = []
    for concurrency, per_algorithm in summaries_by_point.items():
        for algorithm, summaries in per_algorithm.items():
            point = {"concurrency": concurrency, "algorithm": algorithm}
            for metric in (
                "average_latency_ms",
                "p90_latency_ms",
                "throughput_tasks_per_s",
            ):
                values = [row[metric] for row in summaries if row[metric] is not None]
                point[f"mean_{metric}"] = mean(values) if values else None
                point[f"std_{metric}"] = stdev(values) if len(values) > 1 else 0.0
            points.append(point)

    result = {
        "scenario": scenario,
        "concurrency_step": concurrency_step,
        "repetitions": repetitions,
        "comparison": comparison,
        "estimated_runtime_s": estimate_s,
        "points": points,
    }
    if output_dir is not None:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        fields = ["concurrency", "algorithm"] + [
            field
            for metric in (
                "average_latency_ms",
                "p90_latency_ms",
                "throughput_tasks_per_s",
            )
            for field in (f"mean_{metric}", f"std_{metric}")
        ]
        _write_csv(target_dir / "concurrency_sweep.csv", fields, points)
        result["csv"] = str(target_dir / "concurrency_sweep.csv")
    return result


def run_benchmark(
    scenario="mixed",
    concurrency=20,
    repetitions=3,
    comparison="both",
    output_dir=None,
    classical_rate_mode=None,
    classical_rate=None,
    contention_model=CONTENTION_MODEL,
    speedup=1.0,
    load_scope=LOAD_SCOPE,
    idle_service_rate_n_override=IDLE_SERVICE_RATE_N_OVERRIDE,
):
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if not 1 <= concurrency <= 200:
        raise ValueError("Concurrency must be between 1 and 200")
    if not 1 <= repetitions <= 20:
        raise ValueError("Repetitions must be between 1 and 20")
    if comparison not in {"both", "classical", "adaptive"}:
        raise ValueError("Invalid comparison mode")
    if load_scope not in {"process", "host"}:
        raise ValueError("load_scope must be 'process' or 'host'")

    cached_rate = load_optimal_classical_rates().get(scenario, {}).get("rate")
    if classical_rate_mode is None:
        classical_rate_mode = (
            "measured" if cached_rate is not None else "paper_preset"
        )
    if classical_rate_mode not in {"paper_preset", "measured", "manual"}:
        raise ValueError("Invalid classical_rate_mode")
    if classical_rate_mode == "manual":
        if classical_rate is None or not math.isfinite(classical_rate) or classical_rate <= 0:
            raise ValueError("manual mode requires a positive classical_rate")
        selected_classical_rate = float(classical_rate)
    elif classical_rate_mode == "measured":
        if cached_rate is None:
            raise ValueError("No measured classical rate is cached for this scenario")
        selected_classical_rate = float(cached_rate)
    else:
        selected_classical_rate = PAPER_CLASSICAL_RATE_PRESETS[scenario]

    algorithms = (
        ["classical", "adaptive"]
        if comparison == "both"
        else [comparison]
    )

    all_records = []
    all_summaries = []
    all_rate_diagnostics = []
    plan = []
    if scenario == "dynamic":
        if not math.isfinite(speedup) or speedup <= 0:
            raise ValueError("speedup must be positive and finite")
        for step in range(DAILY_ENVELOPE_STEPS):
            step_concurrency = daily_envelope_concurrency(step, speedup)
            for trial in range(1, repetitions + 1):
                seed = 42 + step * repetitions + trial
                plan.append((step, step_concurrency, trial, seed))
    else:
        plan.extend(
            (None, concurrency, trial, 42 + trial)
            for trial in range(1, repetitions + 1)
        )

    for dynamic_step, trial_concurrency, trial, workload_seed in plan:
        trial_algorithms = (
            algorithms
            if (trial + (dynamic_step or 0)) % 2 == 1 or len(algorithms) == 1
            else list(reversed(algorithms))
        )
        paired_workload = generate_workload(
            scenario,
            trial_concurrency,
            seed=workload_seed,
        )
        execution_order = ",".join(trial_algorithms)
        for algorithm in trial_algorithms:
            records, summary, diagnostics = run_trial(
                scenario,
                trial_concurrency,
                algorithm,
                trial,
                workload=paired_workload,
                workload_seed=workload_seed,
                algorithm_order=execution_order,
                classical_rate=(
                    selected_classical_rate
                    if algorithm == "classical"
                    else None
                ),
                contention_model=contention_model,
                load_scope=load_scope,
                idle_service_rate_override=idle_service_rate_n_override,
                rate_mode=(
                    classical_rate_mode
                    if algorithm == "classical"
                    else None
                ),
            )
            if dynamic_step is not None:
                summary["dynamic_step"] = dynamic_step
            all_records.extend(records)
            all_summaries.append(summary)
            all_rate_diagnostics.extend(diagnostics)

    result_dir = (
        Path(output_dir)
        if output_dir is not None
        else Path(__file__).resolve().parent / "results"
    )
    result_dir.mkdir(parents=True, exist_ok=True)

    task_csv = result_dir / "task_results.csv"
    summary_csv = result_dir / "benchmark_summary.csv"
    diagnostic_csv = result_dir / "rate_diagnostics.csv"
    _write_csv(task_csv, TASK_FIELDS, all_records)
    _write_csv(summary_csv, SUMMARY_FIELDS, all_summaries)
    _write_csv(
        diagnostic_csv,
        RATE_DIAGNOSTIC_FIELDS,
        all_rate_diagnostics,
    )

    dynamic_steps = []
    if scenario == "dynamic":
        for step in range(DAILY_ENVELOPE_STEPS):
            step_rows = [
                row for row in all_summaries
                if row.get("dynamic_step") == step
            ]
            concurrency_for_step = daily_envelope_concurrency(step, speedup)
            for algorithm in algorithms:
                rows = [row for row in step_rows if row["algorithm"] == algorithm]
                dynamic_steps.append({
                    "step": step,
                    "concurrency": concurrency_for_step,
                    "algorithm": algorithm,
                    "mean_latency_ms": mean(
                        row["average_latency_ms"] for row in rows
                        if row["average_latency_ms"] is not None
                    ) if any(row["average_latency_ms"] is not None for row in rows) else None,
                    "p90_latency_ms": mean(
                        row["p90_latency_ms"] for row in rows
                        if row["p90_latency_ms"] is not None
                    ) if any(row["p90_latency_ms"] is not None for row in rows) else None,
                    "throughput_tasks_per_s": mean(
                        row["throughput_tasks_per_s"] for row in rows
                    ) if rows else None,
                    "classical_rate": selected_classical_rate,
                    "adaptive_rate_min": min(
                        (row["minimum_observed_rate"] for row in rows
                         if row["algorithm"] == "adaptive"),
                        default=None,
                    ),
                    "adaptive_rate_mean": mean(
                        row["average_observed_rate"] for row in rows
                        if row["algorithm"] == "adaptive"
                    ) if any(row["algorithm"] == "adaptive" for row in rows) else None,
                    "adaptive_rate_max": max(
                        (row["maximum_observed_rate"] for row in rows
                         if row["algorithm"] == "adaptive"),
                        default=None,
                    ),
                    "adaptive_min_clamp_fraction": (
                        sum(row["minimum_rate_clamps"] for row in rows
                            if row["algorithm"] == "adaptive")
                        / max(sum(row["controller_evaluations"] for row in rows
                                  if row["algorithm"] == "adaptive"), 1)
                    ),
                    "adaptive_max_clamp_fraction": (
                        sum(row["maximum_rate_clamps"] for row in rows
                            if row["algorithm"] == "adaptive")
                        / max(sum(row["controller_evaluations"] for row in rows
                                  if row["algorithm"] == "adaptive"), 1)
                    ),
                })
        dynamic_path = result_dir / "dynamic_steps.csv"
        _write_csv(dynamic_path, DYNAMIC_STEP_FIELDS, dynamic_steps)

    relative_differences = None
    if scenario == "dynamic" and {"classical", "adaptive"}.issubset(algorithms):
        per_step = []
        for step in range(DAILY_ENVELOPE_STEPS):
            pair = {
                row["algorithm"]: row
                for row in dynamic_steps if row["step"] == step
            }
            classical = pair.get("classical")
            adaptive = pair.get("adaptive")
            if not classical or not adaptive:
                continue
            def relative(classical_value, adaptive_value, inverse=False):
                if not classical_value:
                    return None
                numerator = (
                    classical_value - adaptive_value
                    if inverse else adaptive_value - classical_value
                )
                return numerator / classical_value
            per_step.append({
                "step": step,
                "latency_relative_difference": relative(
                    classical["mean_latency_ms"], adaptive["mean_latency_ms"], True
                ),
                "p90_relative_difference": relative(
                    classical["p90_latency_ms"], adaptive["p90_latency_ms"], True
                ),
                "throughput_relative_difference": relative(
                    classical["throughput_tasks_per_s"],
                    adaptive["throughput_tasks_per_s"],
                ),
            })
        relative_differences = {
            "per_step": per_step,
            "mean_latency_relative_difference": mean(
                row["latency_relative_difference"] for row in per_step
                if row["latency_relative_difference"] is not None
            ),
            "mean_p90_relative_difference": mean(
                row["p90_relative_difference"] for row in per_step
                if row["p90_relative_difference"] is not None
            ),
            "mean_throughput_relative_difference": mean(
                row["throughput_relative_difference"] for row in per_step
                if row["throughput_relative_difference"] is not None
            ),
        }

    return {
        "scenario": scenario,
        "concurrency": concurrency,
        "repetitions": repetitions,
        "algorithms": algorithms,
        "classical_rate_mode": classical_rate_mode,
        "classical_rate": selected_classical_rate,
        "contention_model": contention_model,
        "load_scope": load_scope,
        "summaries": all_summaries,
        "task_results": all_records,
        "task_csv": str(task_csv),
        "summary_csv": str(summary_csv),
        "diagnostic_csv": str(diagnostic_csv),
        "dynamic_steps": dynamic_steps,
        "dynamic_relative_differences": relative_differences,
        "rate_diagnostics": all_rate_diagnostics,
    }
