import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import psutil

import monitoring.system_monitor as system_monitor
from monitoring.system_monitor import SystemMonitor, get_system_metrics


class SystemMonitorTests(unittest.TestCase):
    def setUp(self):
        with system_monitor._cpu_lock:
            system_monitor._cpu_sample_ready = False
            system_monitor._process_cpu_sample_ready = False

    def test_process_scope_uses_process_cpu_and_memory_budget(self):
        process = SimpleNamespace(
            cpu_percent=lambda interval=None: 400.0,
            memory_info=lambda: SimpleNamespace(rss=512 * 1024 ** 2),
        )
        with patch.object(
            system_monitor.psutil,
            "cpu_percent",
            side_effect=[10.0, 20.0],
        ), patch.object(system_monitor.psutil, "cpu_count", return_value=8):
            first = get_system_metrics(
                active_resources=2,
                total_resources=4,
                process=process,
            )
            second = get_system_metrics(
                active_resources=2,
                total_resources=4,
                process=process,
            )

        self.assertIsNone(first["cpu"])
        self.assertAlmostEqual(second["cpu"], 0.5)
        self.assertAlmostEqual(second["memory"], 0.5)
        self.assertAlmostEqual(second["host_cpu_utilization"], 0.2)
        self.assertEqual(first["resource_usage"], 0.5)

    def test_host_scope_uses_host_values_but_keeps_process_diagnostics(self):
        process = SimpleNamespace(
            cpu_percent=lambda interval=None: 100.0,
            memory_info=lambda: SimpleNamespace(rss=1234),
        )
        with (
            patch.object(system_monitor.psutil, "cpu_percent", return_value=40.0),
            patch.object(system_monitor.psutil, "cpu_count", return_value=4),
            patch.object(
                system_monitor.psutil,
                "virtual_memory",
                return_value=SimpleNamespace(percent=90.0),
            ),
        ):
            get_system_metrics(load_scope="host", process=process)
            metrics = get_system_metrics(load_scope="host", process=process)
        self.assertAlmostEqual(metrics["cpu"], 0.4)
        self.assertAlmostEqual(metrics["memory"], 0.9)
        self.assertAlmostEqual(metrics["process_cpu_utilization"], 0.25)

    def test_metric_failures_are_marked_unavailable(self):
        with (
            patch.object(
                system_monitor.psutil,
                "cpu_percent",
                side_effect=OSError("cpu unavailable"),
            ),
            patch.object(
                system_monitor.psutil,
                "virtual_memory",
                side_effect=psutil.Error("memory unavailable"),
            ),
            patch.object(
                system_monitor.psutil,
                "Process",
                side_effect=psutil.Error("process unavailable"),
            ),
        ):
            metrics = get_system_metrics(
                active_resources=10,
                total_resources=8,
            )

        self.assertIsNone(metrics["cpu"])
        self.assertIsNone(metrics["memory"])
        self.assertEqual(metrics["resource_usage"], 1.0)

    def test_background_sampler_shuts_down_and_exposes_samples(self):
        process = SimpleNamespace(
            cpu_percent=lambda interval=None: 25.0,
            memory_info=lambda: SimpleNamespace(rss=1024),
        )
        with (
            patch.object(system_monitor.psutil, "Process", return_value=process),
            patch.object(system_monitor.psutil, "cpu_percent", return_value=25.0),
            patch.object(system_monitor.psutil, "cpu_count", return_value=1),
        ):
            monitor = SystemMonitor(
                active_workers=lambda: 1,
                total_workers=2,
                sampling_interval_s=0.01,
            )
            monitor.start()

            deadline = time.monotonic() + 1
            while monitor.averages()["cpu"] is None:
                if time.monotonic() >= deadline:
                    self.fail("CPU sampler did not produce a reading")
                threading.Event().wait(0.005)

            monitor.stop()

        self.assertIsNone(monitor._thread)
        self.assertAlmostEqual(monitor.averages()["cpu"], 0.25)
        self.assertEqual(monitor.averages()["resource_usage"], 0.5)

    def test_load_calculator_can_exclude_unavailable_cpu(self):
        from algorithms.load_calculator import calculate_load

        result = calculate_load(cpu=None, memory=0.5, resources=0.25)
        self.assertGreaterEqual(result["load"], 0.0)
        self.assertLessEqual(result["load"], 1.0)
        self.assertIsNone(result["states"]["cpu"])

        unavailable = calculate_load(cpu=None, memory=None, resources=None)
        self.assertIsNone(unavailable["load"])


if __name__ == "__main__":
    unittest.main()
