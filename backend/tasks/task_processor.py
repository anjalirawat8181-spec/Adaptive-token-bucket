
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field


@dataclass
class Task:
    task_id: int
    task_type: str
    duration_ms: float
    submitted_at: float = field(default_factory=time.perf_counter)


class TaskProcessor:
    def __init__(self, workers=8):
        self.tasks = queue.Queue()
        self.results = []
        self.lock = threading.Lock()
        self.workers = []

        for _ in range(workers):
            thread = threading.Thread(
                target=self._worker,
                daemon=True,
            )
            thread.start()
            self.workers.append(thread)

    def submit(self, task):
        future = Future()
        self.tasks.put((task, future))
        return future

    def _worker(self):
        while True:
            task, future = self.tasks.get()

            try:
                started = time.perf_counter()
                wait_ms = (
                    started - task.submitted_at
                ) * 1000

                time.sleep(task.duration_ms / 1000)

                completed = time.perf_counter()
                latency_ms = (
                    completed - task.submitted_at
                ) * 1000

                result = {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "queue_wait_ms": wait_ms,
                    "latency_ms": latency_ms,
                    "processing_ms": (
                        completed - started
                    ) * 1000,
                }

                with self.lock:
                    self.results.append(result)

                future.set_result(result)

            except Exception as exc:
                future.set_exception(exc)

            finally:
                self.tasks.task_done()

    def queue_length(self):
        return self.tasks.qsize()
