import csv
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import experiments.benchmark as benchmark


class WorkerTrackerTests(unittest.TestCase):
    def test_idle_partial_full_and_return_to_idle_utilization(self):
        tracker = benchmark.WorkerTracker(total_workers=4)
        self.assertEqual(tracker.snapshot()["worker_utilization"], 0.0)

        for _ in range(4):
            tracker.task_queued()
        tracker.task_started()
        self.assertEqual(tracker.snapshot()["worker_utilization"], 0.25)
        tracker.task_started()
        tracker.task_started()
        tracker.task_started()
        self.assertEqual(tracker.snapshot()["worker_utilization"], 1.0)
        self.assertEqual(tracker.snapshot()["queued_tasks"], 0)

        for _ in range(4):
            tracker.task_finished()
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["worker_utilization"], 0.0)
        self.assertEqual(snapshot["outstanding_tasks"], 0)

    def test_worker_count_is_balanced_when_task_raises(self):
        tracker = benchmark.WorkerTracker(total_workers=2)
        tracker.task_queued()
        task = {
            "task_id": 1,
            "task_type": "simple",
            "duration_ms": 5,
            "workload_id": "simple-1-seed-43",
            "scheduled_arrival_offset_s": 0.0,
            "scheduled_arrival_s": benchmark.time.perf_counter() - 0.02,
        }
        actual_arrival_at = benchmark.time.perf_counter() - 0.015
        submitted_at = benchmark.time.perf_counter() - 0.01
        admitted_at = benchmark.time.perf_counter() - 0.005
        with patch.object(benchmark.time, "sleep", side_effect=RuntimeError("failed")):
            result = benchmark._process_task(
                task,
                actual_arrival_at=actual_arrival_at,
                submitted_at=submitted_at,
                token_requested_at=benchmark.time.perf_counter() - 0.007,
                admitted_at=admitted_at,
                tracker=tracker,
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("RuntimeError", result["error"])
        self.assertEqual(tracker.snapshot()["active_workers"], 0)
        self.assertEqual(tracker.snapshot()["outstanding_tasks"], 0)
        self.assertGreaterEqual(result["latency_ms"], result["admission_delay_ms"])

    def test_outstanding_task_signal_tracks_stable_and_bursty_load(self):
        tracker = benchmark.WorkerTracker(total_workers=4)
        observed = []

        for _ in range(4):
            tracker.task_queued()
            observed.append(
                tracker.snapshot()["outstanding_tasks"] / tracker.total_workers
            )
        self.assertEqual(observed, [0.25, 0.5, 0.75, 1.0])

        for _ in range(4):
            tracker.task_started()
        self.assertEqual(
            tracker.snapshot()["outstanding_tasks"] / tracker.total_workers,
            1.0,
        )

        for _ in range(4):
            tracker.task_finished()
        self.assertEqual(
            tracker.snapshot()["outstanding_tasks"] / tracker.total_workers,
            0.0,
        )


class BenchmarkTests(unittest.TestCase):
    def test_trial_metrics_use_successful_records_and_wall_time(self):
        records, summary, diagnostics = benchmark.run_trial(
            scenario="simple",
            concurrency=3,
            algorithm="classical",
            trial_number=1,
        )
        successful = [row for row in records if row["status"] == "success"]

        self.assertEqual(summary["completed_tasks"], len(successful))
        self.assertEqual(summary["failed_tasks"], 0)
        self.assertAlmostEqual(
            summary["average_latency_ms"],
            sum(row["latency_ms"] for row in successful) / len(successful),
        )
        self.assertEqual(
            summary["throughput_tasks_per_s"],
            summary["completed_tasks"] / summary["elapsed_s"],
        )
        self.assertEqual(summary["p95_latency_ms"], max(
            row["latency_ms"] for row in successful
        ))
        for row in successful:
            self.assertAlmostEqual(
                row["latency_ms"],
                (row["completed_s"] - row["actual_arrival_s"]) * 1000,
            )
            self.assertAlmostEqual(
                row["admission_delay_ms"],
                (row["admitted_s"] - row["actual_arrival_s"]) * 1000,
            )
            self.assertAlmostEqual(
                row["queue_wait_ms"],
                (row["started_s"] - row["admitted_s"]) * 1000,
            )
            self.assertAlmostEqual(
                row["token_admission_wait_ms"],
                (row["admitted_s"] - row["token_requested_s"]) * 1000,
            )
            self.assertAlmostEqual(
                row["controller_update_ms"],
                (row["token_requested_s"] - row["submitted_s"]) * 1000,
            )
        utilization = summary["average_worker_utilization"]
        self.assertGreater(utilization, 0.0)
        self.assertLessEqual(utilization, 1.0)
        self.assertEqual(diagnostics, [])

    def test_failed_execution_is_not_counted_as_completed(self):
        with patch.object(
            benchmark.time,
            "sleep",
            side_effect=RuntimeError("simulated task failure"),
        ):
            records, summary, _ = benchmark.run_trial(
                scenario="simple",
                concurrency=1,
                algorithm="classical",
                trial_number=1,
                idle_service_rate_override=1000.0,
            )

        self.assertEqual(records[0]["status"], "failed")
        self.assertEqual(summary["completed_tasks"], 0)
        self.assertEqual(summary["failed_tasks"], 1)
        self.assertEqual(summary["throughput_tasks_per_s"], 0.0)
        self.assertIsNone(summary["average_latency_ms"])

    def test_arrival_schedule_advances_while_admission_is_blocked(self):
        calls = 0

        def delayed_acquire(bucket, timeout=5.0):
            nonlocal calls
            calls += 1
            if calls == 1:
                threading.Event().wait(0.18)
            return True

        with patch.object(benchmark.TokenBucket, "acquire", delayed_acquire):
            records, _, diagnostics = benchmark.run_trial(
                scenario="dynamic",
                concurrency=3,
                algorithm="adaptive",
                trial_number=1,
            )

        first = records[0]
        second = records[1]
        self.assertLess(second["actual_arrival_s"], first["admitted_s"])
        self.assertGreaterEqual(
            second["actual_arrival_s"], second["scheduled_arrival_s"]
        )
        self.assertEqual(
            [row["scheduled_arrival_offset_s"] for row in records],
            [0.0, 0.0, 0.0],
        )
        self.assertEqual(len(diagnostics), 3)

    def test_dynamic_envelope_and_rate_calibration_override(self):
        self.assertEqual(benchmark.daily_envelope_concurrency(0), 20)
        self.assertEqual(benchmark.daily_envelope_concurrency(9), 200)
        self.assertEqual(
            benchmark.calibrate_idle_service_rate(20, override=123.0),
            123.0,
        )
        workload = benchmark.generate_workload("dynamic", 4, seed=11)
        self.assertEqual(
            [task["scheduled_arrival_offset_s"] for task in workload],
            [0.0] * 4,
        )

    def test_idle_calibration_is_cached_by_cost_and_configuration(self):
        key = (20.0, 2, 2, False)
        benchmark._IDLE_SERVICE_RATE_CACHE.pop(key, None)
        with patch.object(benchmark.time, "sleep"):
            first = benchmark.calibrate_idle_service_rate(
                20,
                workers=2,
                batch_size=2,
                override=None,
                contention_model=False,
            )
        benchmark._IDLE_SERVICE_RATE_CACHE[key] = 777.0
        second = benchmark.calibrate_idle_service_rate(
            20,
            workers=2,
            batch_size=2,
            override=None,
            contention_model=False,
        )
        self.assertGreater(first, 0)
        self.assertEqual(second, 777.0)

    def test_processor_sharing_model_scales_each_slice_by_active_workers(self):
        class Tracker:
            def task_started(self):
                return None

            def task_finished(self):
                return None

            def snapshot(self):
                return {"active_workers": 8}

        task = {
            "task_id": 1,
            "task_type": "simple",
            "duration_ms": 4,
            "workload_id": "test",
            "scheduled_arrival_offset_s": 0,
            "scheduled_arrival_s": 0,
        }
        with patch.object(benchmark.time, "sleep") as sleeper:
            benchmark._process_task(task, 0, 0, 0, 0, Tracker(), True)
        self.assertEqual(sleeper.call_count, 4)

    def test_optimal_rate_probe_selects_minimum_latency_and_caches_table(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "optimal_rates.json"

            def trial(*args, classical_rate=None, **kwargs):
                latency = abs(classical_rate - 100)
                return [], {
                    "average_latency_ms": latency,
                    "throughput_tasks_per_s": 10.0,
                }, []

            with patch.object(benchmark, "run_trial", side_effect=trial):
                result = benchmark.find_optimal_classical_rate(
                    "simple",
                    candidate_rates=[50, 100, 150],
                    concurrency_levels=[5],
                    repetitions=1,
                    cache_path=cache,
                )
            self.assertEqual(result["rate"], 100.0)
            self.assertEqual(len(result["sweep"]), 3)
            self.assertEqual(
                benchmark.load_optimal_classical_rates(cache)["simple"]["rate"],
                100.0,
            )

    def test_concurrency_sweep_rejects_runtime_over_fifteen_minutes(self):
        with self.assertRaisesRegex(ValueError, "Estimated sweep runtime"):
            benchmark.run_concurrency_sweep(
                scenario="complex",
                concurrency_step=1,
                repetitions=20,
            )

    def test_dynamic_run_emits_paired_per_step_p90_and_relative_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(benchmark, "DAILY_ENVELOPE_STEPS", 2),
                patch.object(benchmark, "daily_envelope_concurrency", return_value=20),
                patch.object(benchmark, "calibrate_idle_service_rate", return_value=500.0),
            ):
                result = benchmark.run_benchmark(
                    scenario="dynamic",
                    repetitions=1,
                    comparison="both",
                    output_dir=directory,
                )
                dynamic_csv_exists = Path(directory, "dynamic_steps.csv").is_file()
        self.assertEqual(len(result["dynamic_steps"]), 4)
        self.assertTrue(all(
            row["p90_latency_ms"] is not None
            for row in result["dynamic_steps"]
        ))
        self.assertEqual(len(result["dynamic_relative_differences"]["per_step"]), 2)
        self.assertTrue(dynamic_csv_exists)

    def test_algorithms_receive_paired_deterministic_workloads(self):
        generate_workload = benchmark.generate_workload
        with patch.object(
            benchmark,
            "generate_workload",
            wraps=generate_workload,
        ) as generate:
            classical, _, _ = benchmark.run_trial(
                "mixed", 2, "classical", 3
            )
            adaptive, _, _ = benchmark.run_trial(
                "mixed", 2, "adaptive", 3
            )

        self.assertEqual(generate.call_args_list[0], generate.call_args_list[1])
        self.assertEqual(
            [
                (row["task_id"], row["task_type"], row["duration_ms"],
                 row["scheduled_arrival_offset_s"])
                for row in classical
            ],
            [
                (row["task_id"], row["task_type"], row["duration_ms"],
                 row["scheduled_arrival_offset_s"])
                for row in adaptive
            ],
        )
        self.assertEqual(classical[0]["workload_seed"], adaptive[0]["workload_seed"])

    def test_homogeneous_scenario_keeps_paper_task_cost_bounds_fixed(self):
        _, summary, diagnostics = benchmark.run_trial(
            "simple",
            4,
            "adaptive",
            1,
            idle_service_rate_override=1000.0,
        )
        self.assertEqual(summary["adaptive_reference_task_cost_ms"], 5)
        self.assertEqual({row["minimum_rate"] for row in diagnostics}, {200.0})
        self.assertEqual({row["maximum_rate"] for row in diagnostics}, {1600.0})

    def test_csvs_match_benchmark_records_without_overwriting_project_results(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = benchmark.run_benchmark(
                scenario="simple",
                concurrency=2,
                repetitions=2,
                comparison="both",
                output_dir=temporary_directory,
            )
            task_path = Path(result["task_csv"])
            summary_path = Path(result["summary_csv"])
            diagnostic_path = Path(result["diagnostic_csv"])
            with task_path.open(encoding="utf-8", newline="") as source:
                task_rows = list(csv.DictReader(source))
            with summary_path.open(encoding="utf-8", newline="") as source:
                summary_rows = list(csv.DictReader(source))
            with diagnostic_path.open(encoding="utf-8", newline="") as source:
                diagnostic_rows = list(csv.DictReader(source))

        self.assertEqual(len(summary_rows), 4)
        self.assertEqual(len(task_rows), len(result["task_results"]))
        self.assertEqual(len(result["summaries"]), 4)
        self.assertEqual(
            len(diagnostic_rows),
            sum(s["controller_evaluations"] for s in result["summaries"]),
        )
        self.assertIn("proposed_rate", diagnostic_rows[0])
        self.assertIn("skip_reason", diagnostic_rows[0])
        for row in summary_rows:
            self.assertIn("failed_tasks", row)
            self.assertIn("average_worker_utilization", row)
        for row in task_rows:
            self.assertIn(row["status"], {"success", "failed"})
            self.assertIn("admission_delay_ms", row)

    def test_api_preserves_result_contract_and_csv_downloads(self):
        from api import (
            ExperimentRequest,
            download_experiment_result,
            run_experiment,
        )
        from fastapi.responses import FileResponse

        expected = {
            "scenario": "simple",
            "concurrency": 2,
            "repetitions": 1,
            "algorithms": ["classical"],
            "summaries": [],
            "task_results": [],
            "task_csv": "task_results.csv",
            "summary_csv": "benchmark_summary.csv",
        }
        with patch("api.run_benchmark", return_value=dict(expected)):
            response = run_experiment(ExperimentRequest(
                scenario="simple",
                concurrency=2,
                repetitions=1,
                comparison="classical",
            ))
        self.assertEqual(response["scenario"], "simple")
        self.assertEqual(
            response["task_csv_url"],
            "/api/experiments/download/task_results.csv",
        )
        self.assertEqual(
            response["summary_csv_url"],
            "/api/experiments/download/benchmark_summary.csv",
        )
        self.assertEqual(
            response["diagnostic_csv_url"],
            "/api/experiments/download/rate_diagnostics.csv",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "task_results.csv"
            csv_path.write_text("task_id,status\n1,success\n", encoding="utf-8")
            with patch("api.RESULTS_DIR", Path(temporary_directory)):
                download = download_experiment_result("task_results.csv")
        self.assertIsInstance(download, FileResponse)
        self.assertEqual(download.media_type, "text/csv")

    def test_fastapi_benchmark_and_csv_download_round_trip(self):
        import api
        from fastapi.testclient import TestClient
        from main import app

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.object(api, "RESULTS_DIR", Path(temporary_directory)):
                with TestClient(app) as client:
                    health = client.get("/api/health")
                    response = client.post(
                        "/api/experiments/run",
                        json={
                            "scenario": "simple",
                            "concurrency": 2,
                            "repetitions": 1,
                            "comparison": "both",
                        },
                    )
                    task_csv = client.get(
                        "/api/experiments/download/task_results.csv"
                    )
                    summary_csv = client.get(
                        "/api/experiments/download/benchmark_summary.csv"
                    )
                    diagnostic_csv = client.get(
                        "/api/experiments/download/rate_diagnostics.csv"
                    )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["task_results"]), 4)
        self.assertEqual(len(body["summaries"]), 2)
        self.assertEqual(body["rate_diagnostics_count"], 2)
        self.assertEqual(task_csv.status_code, 200)
        self.assertEqual(summary_csv.status_code, 200)
        self.assertEqual(diagnostic_csv.status_code, 200)
        self.assertEqual(
            len(list(csv.DictReader(task_csv.text.splitlines()))), 4
        )
        self.assertEqual(
            len(list(csv.DictReader(summary_csv.text.splitlines()))), 2
        )
        self.assertEqual(
            len(list(csv.DictReader(diagnostic_csv.text.splitlines()))), 2
        )
        csv_summaries = list(csv.DictReader(summary_csv.text.splitlines()))
        body_summaries = {
            row["algorithm"]: row for row in body["summaries"]
        }
        for row in csv_summaries:
            self.assertAlmostEqual(
                float(row["throughput_tasks_per_s"]),
                body_summaries[row["algorithm"]]["throughput_tasks_per_s"],
            )
        csv_tasks = list(csv.DictReader(task_csv.text.splitlines()))
        self.assertEqual(
            {row["workload_seed"] for row in csv_tasks},
            {str(row["workload_seed"]) for row in body["task_results"]},
        )

    def test_optimal_rate_api_reads_and_writes_cached_rate_results(self):
        import api
        from fastapi.testclient import TestClient
        from main import app

        with (
            patch.object(
                api,
                "find_optimal_classical_rate",
                return_value={"scenario": "simple", "rate": 100.0, "sweep": []},
            ) as probe,
            patch.object(
                api,
                "load_optimal_classical_rates",
                return_value={"simple": {"scenario": "simple", "rate": 100.0}},
            ),
            TestClient(app) as client,
        ):
            posted = client.post(
                "/api/experiments/optimal-rate",
                json={
                    "scenario": "simple",
                    "candidate_rates": [50, 100],
                    "concurrency_levels": [10],
                    "repetitions": 1,
                },
            )
            retrieved = client.get("/api/experiments/optimal-rate/simple")
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["rate"], 100.0)
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json()["rate"], 100.0)
        self.assertEqual(probe.call_args.kwargs["concurrency_levels"], [10])


if __name__ == "__main__":
    unittest.main()
