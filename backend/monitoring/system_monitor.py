import math
import threading
import time
from statistics import mean

import psutil


_cpu_lock = threading.Lock()
_cpu_sample_ready = False
_process_cpu_sample_ready = False
LOAD_SCOPE = "process"
SERVICE_MEMORY_BUDGET_BYTES = 1024 ** 3


def _read_host_cpu_percent():
    global _cpu_sample_ready

    with _cpu_lock:
        percent = psutil.cpu_percent(interval=None)
        if not _cpu_sample_ready:
            _cpu_sample_ready = True
            return None
    if not math.isfinite(percent):
        return None
    return min(max(percent / 100.0, 0.0), 1.0)


def _read_process_cpu_percent(process):
    global _process_cpu_sample_ready

    with _cpu_lock:
        percent = process.cpu_percent(interval=None)
        if not _process_cpu_sample_ready:
            _process_cpu_sample_ready = True
            return None
    cpu_count = psutil.cpu_count()
    if not math.isfinite(percent) or not cpu_count:
        return None
    return min(max(percent / (100.0 * cpu_count), 0.0), 1.0)


def get_system_metrics(
    active_resources=0,
    total_resources=8,
    load_scope=LOAD_SCOPE,
    process=None,
):
    if load_scope not in {"process", "host"}:
        raise ValueError("load_scope must be 'process' or 'host'")
    try:
        process = process or psutil.Process()
        process_cpu = _read_process_cpu_percent(process)
    except (psutil.Error, OSError, NotImplementedError, TypeError, ValueError):
        process_cpu = None

    try:
        rss = process.memory_info().rss if process is not None else None
        process_memory = (
            min(max(rss / SERVICE_MEMORY_BUDGET_BYTES, 0.0), 1.0)
            if rss is not None and math.isfinite(rss)
            else None
        )
    except (psutil.Error, OSError, NotImplementedError, TypeError, ValueError):
        process_memory = None

    try:
        host_cpu = _read_host_cpu_percent()
    except (psutil.Error, OSError, NotImplementedError, TypeError, ValueError):
        host_cpu = None
    try:
        percent = psutil.virtual_memory().percent
        host_memory = (
            min(max(percent / 100.0, 0.0), 1.0)
            if math.isfinite(percent)
            else None
        )
    except (psutil.Error, OSError, NotImplementedError, TypeError, ValueError):
        host_memory = None

    cpu, memory = (
        (process_cpu, process_memory)
        if load_scope == "process"
        else (host_cpu, host_memory)
    )

    if (
        isinstance(total_resources, (int, float))
        and math.isfinite(total_resources)
        and total_resources > 0
        and isinstance(active_resources, (int, float))
        and math.isfinite(active_resources)
    ):
        resource_usage = min(
            max(active_resources / total_resources, 0.0),
            1.0,
        )
    else:
        resource_usage = None

    return {
        "cpu": cpu,
        "memory": memory,
        "process_cpu_utilization": process_cpu,
        "process_memory_utilization": process_memory,
        "host_cpu_utilization": host_cpu,
        "host_memory_utilization": host_memory,
        "resource_usage": resource_usage,
    }


class SystemMonitor:
    def __init__(
        self,
        active_workers,
        total_workers,
        sampling_interval_s=0.1,
        load_scope=LOAD_SCOPE,
    ):
        if total_workers < 1:
            raise ValueError("total_workers must be positive")
        if (
            not math.isfinite(sampling_interval_s)
            or sampling_interval_s <= 0
        ):
            raise ValueError("sampling_interval_s must be positive and finite")

        self._active_workers = active_workers
        self._total_workers = total_workers
        self.load_scope = load_scope
        self._process = psutil.Process()
        self._interval = sampling_interval_s
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._metrics = get_system_metrics(
            active_resources=active_workers(),
            total_resources=total_workers,
            load_scope=load_scope,
            process=self._process,
        )
        self._sampled_at_s = time.perf_counter()
        self._samples = {
            "cpu": [],
            "memory": [],
            "resource_usage": [],
            "process_cpu_utilization": [],
            "process_memory_utilization": [],
            "host_cpu_utilization": [],
            "host_memory_utilization": [],
        }

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_periodically,
            name="system-monitor",
            daemon=True,
        )
        self._thread.start()

    def _sample_periodically(self):
        while not self._stop_event.wait(self._interval):
            metrics = get_system_metrics(
                active_resources=self._active_workers(),
                total_resources=self._total_workers,
                load_scope=self.load_scope,
                process=self._process,
            )
            sampled_at = time.perf_counter()
            with self._lock:
                self._metrics = metrics
                self._sampled_at_s = sampled_at
                for name, value in metrics.items():
                    if value is not None:
                        self._samples[name].append(value)

    def snapshot(self):
        with self._lock:
            snapshot = dict(self._metrics)
            sampled_at = self._sampled_at_s
        snapshot["sampled_at_s"] = sampled_at
        snapshot["sample_age_s"] = max(
            time.perf_counter() - sampled_at,
            0.0,
        )
        return snapshot

    def averages(self):
        with self._lock:
            return {
                name: mean(values) if values else None
                for name, values in self._samples.items()
            }

    def stop(self):
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(1.0, self._interval * 2))
        if self._thread.is_alive():
            raise RuntimeError("System monitoring thread did not shut down")
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
