
import csv
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

from algorithms.token_bucket import TokenBucket
from algorithms.adaptive_token_bucket import AdaptiveRateController
from algorithms.load_calculator import calculate_load, load_rank
from monitoring.system_monitor import get_system_metrics


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

MAX_WORKERS = 8
BUCKET_CAPACITY = 8
INITIAL_RATE = 50.0


def generate_workload(scenario_name, concurrency, seed=42):
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    if not 1 <= concurrency <= 200:
        raise ValueError("Concurrency must be between 1 and 200")

    rng = random.Random(seed)
    types = SCENARIOS[scenario_name]
    tasks = []

    for task_id in range(1, concurrency + 1):
        task_type = rng.choice(types)

        if scenario_name == "dynamic":
            fraction = task_id / concurrency
            if fraction <= 1 / 3:
                delay_ms = 100
            elif fraction <= 2 / 3:
                delay_ms = 5
            else:
                delay_ms = 20
        else:
            delay_ms = 0

        tasks.append({
            "task_id": task_id,
            "task_type": task_type,
            "duration_ms": TASK_DURATIONS[task_type],
            "arrival_delay_ms": delay_ms,
        })

    return tasks


def _process_task(task, submitted_at, admitted_at):
    started_at = time.perf_counter()
    time.sleep(task["duration_ms"] / 1000)
    completed_at = time.perf_counter()

    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "duration_ms": task["duration_ms"],
        "submitted_s": submitted_at,
        "admitted_s": admitted_at,
        "started_s": started_at,
        "completed_s": completed_at,
        "queue_wait_ms": (started_at - admitted_at) * 1000,
        "latency_ms": (completed_at - submitted_at) * 1000,
        "processing_ms": (completed_at - started_at) * 1000,
    }


def run_trial(scenario, concurrency, algorithm, trial_number):
    workload = generate_workload(
        scenario,
        concurrency,
        seed=42,
    )

    bucket = TokenBucket(
        rate=INITIAL_RATE,
        capacity=BUCKET_CAPACITY,
    )

    controller = None
    if algorithm == "adaptive":
        # Reference cost for the adaptive controller in mixed workloads.
        controller = AdaptiveRateController(
            initial_rate=INITIAL_RATE,
            max_threads=MAX_WORKERS,
            task_cost_ms=20,
        )
    elif algorithm != "classical":
        raise ValueError("Algorithm must be classical or adaptive")

    records = []
    futures = []
    trial_start = time.perf_counter()

    # Every trial creates a fresh, independent worker pool.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for task in workload:
            if task["arrival_delay_ms"]:
                time.sleep(task["arrival_delay_ms"] / 1000)

            submitted_at = time.perf_counter()

            if controller is not None:
                metrics = get_system_metrics(
                    active_resources=0,
                    total_resources=MAX_WORKERS,
                )
                load_result = calculate_load(
                    cpu=metrics["cpu"],
                    memory=metrics["memory"],
                    resources=metrics["resource_usage"],
                )
                overall_load = load_result["load"]
                rank = load_rank(overall_load)

                update = controller.update(
                    load=overall_load,
                    load_rank=rank,
                    mean_tasks=len(futures) / max(1, MAX_WORKERS),
                    idle_capacity=MAX_WORKERS,
                )
                bucket.set_rate(update["token_rate"])

            if not bucket.acquire(timeout=30):
                raise TimeoutError(
                    f"Token admission timed out for task {task['task_id']}"
                )

            admitted_at = time.perf_counter()
            future = pool.submit(
                _process_task,
                task,
                submitted_at,
                admitted_at,
            )
            futures.append(future)

    for future in as_completed(futures):
        record = future.result()
        record["scenario"] = scenario
        record["algorithm"] = algorithm
        record["concurrency"] = concurrency
        record["trial"] = trial_number
        records.append(record)

    trial_end = time.perf_counter()
    elapsed = trial_end - trial_start

    if not records or elapsed <= 0:
        raise RuntimeError("Benchmark produced no valid measurements")

    summary = {
        "scenario": scenario,
        "algorithm": algorithm,
        "concurrency": concurrency,
        "trial": trial_number,
        "completed_tasks": len(records),
        "elapsed_s": elapsed,
        "average_latency_ms": mean(
            row["latency_ms"] for row in records
        ),
        "throughput_tasks_per_s": len(records) / elapsed,
    }

    return records, summary


def run_benchmark(
    scenario="mixed",
    concurrency=20,
    repetitions=3,
    comparison="both",
):
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if not 1 <= concurrency <= 200:
        raise ValueError("Concurrency must be between 1 and 200")
    if not 1 <= repetitions <= 20:
        raise ValueError("Repetitions must be between 1 and 20")
    if comparison not in {"both", "classical", "adaptive"}:
        raise ValueError("Invalid comparison mode")

    algorithms = (
        ["classical", "adaptive"]
        if comparison == "both"
        else [comparison]
    )

    all_records = []
    all_summaries = []

    for algorithm in algorithms:
        for trial in range(1, repetitions + 1):
            records, summary = run_trial(
                scenario,
                concurrency,
                algorithm,
                trial,
            )
            all_records.extend(records)
            all_summaries.append(summary)

    output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    task_csv = output_dir / "task_results.csv"
    summary_csv = output_dir / "benchmark_summary.csv"

    if all_records:
        with task_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(all_records[0].keys()),
            )
            writer.writeheader()
            writer.writerows(all_records)

    if all_summaries:
        with summary_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(all_summaries[0].keys()),
            )
            writer.writeheader()
            writer.writerows(all_summaries)

    return {
        "scenario": scenario,
        "concurrency": concurrency,
        "repetitions": repetitions,
        "algorithms": algorithms,
        "summaries": all_summaries,
        "task_results": all_records,
        "task_csv": str(task_csv),
        "summary_csv": str(summary_csv),
    }
