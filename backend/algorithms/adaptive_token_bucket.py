
import math
import threading

from algorithms.hmm import RateHMM


class AdaptiveRateController:
    def __init__(
        self,
        initial_rate,
        max_threads,
        task_cost_ms,
        service_rate_n=None,
    ):
        if not math.isfinite(initial_rate) or initial_rate <= 0:
            raise ValueError("initial_rate must be positive and finite")
        if not isinstance(max_threads, int) or max_threads < 1:
            raise ValueError("max_threads must be a positive integer")
        if not math.isfinite(task_cost_ms) or task_cost_ms <= 0:
            raise ValueError("task_cost_ms must be positive and finite")

        self.max_threads = max_threads
        self.task_cost_ms = float(task_cost_ms)
        self.service_rate_n = (
            float(service_rate_n)
            if service_rate_n is not None
            else self.max_threads * 1000.0 / self.task_cost_ms
        )
        if not math.isfinite(self.service_rate_n) or self.service_rate_n <= 0:
            raise ValueError("service_rate_n must be positive and finite")
        self._refresh_rate_bounds()
        if not math.isfinite(self.max_rate):
            raise ValueError("task_cost_ms produces a non-finite maximum rate")
        self.min_rate = 1000.0 / self.task_cost_ms
        self.rate = min(max(float(initial_rate), self.min_rate), self.max_rate)
        self.hmm = RateHMM()
        self._lock = threading.Lock()

    def _refresh_rate_bounds(self):
        self.max_rate = self.max_threads * 1000.0 / self.task_cost_ms
        self.min_rate = 1000.0 / self.task_cost_ms

    def set_task_cost_ms(self, task_cost_ms):
        if not math.isfinite(task_cost_ms) or task_cost_ms <= 0:
            raise ValueError("task_cost_ms must be positive and finite")
        with self._lock:
            self.task_cost_ms = float(task_cost_ms)
            self._refresh_rate_bounds()
            self.rate = min(max(self.rate, self.min_rate), self.max_rate)

    def update(
        self,
        load,
        load_rank,
        ls_tasks_in_system=None,
        idle_capacity=None,
        mean_tasks=None,
    ):
        # mean_tasks remains accepted for callers using the older API. The
        # paper's Ls is a task count for the whole system, not per worker.
        if ls_tasks_in_system is None:
            ls_tasks_in_system = mean_tasks
        if ls_tasks_in_system is None:
            raise ValueError("ls_tasks_in_system must be finite and non-negative")
        if load is None or load_rank is None:
            return {
                "token_rate": self.rate,
                "rate_rank": None,
                "alpha": None,
                "beta": None,
                "min_rate": self.min_rate,
                "max_rate": self.max_rate,
                "remaining_capacity": None,
                "service_capacity": None,
                "delta": None,
                "state_probabilities": None,
                "updated": False,
                "proposed_rate": self.rate,
                "clamp_reason": None,
                "skip_reason": "load measurement unavailable",
            }

        if not math.isfinite(load) or not 0 <= load <= 1:
            raise ValueError("load must be finite and in [0, 1]")
        if load_rank not in range(5):
            raise ValueError("load_rank must be between 0 and 4")
        if not math.isfinite(ls_tasks_in_system) or ls_tasks_in_system < 0:
            raise ValueError("ls_tasks_in_system must be finite and non-negative")
        if (
            not math.isfinite(idle_capacity)
            or not 0 <= idle_capacity <= self.max_threads
        ):
            raise ValueError("idle_capacity must be in [0, max_threads]")

        parameters = {
            1: (1.0, 1.0),
            2: (0.5, 1.0),
            3: (0.0, 0.8),
        }

        with self._lock:
            prediction = self.hmm.predict(load_rank)
            rate_rank = prediction["rate_rank"]
            probabilities = prediction.get("probabilities")
            if rate_rank not in parameters:
                raise ValueError("HMM predicted an invalid rate rank")
            if (
                not isinstance(probabilities, (list, tuple))
                or len(probabilities) != 3
                or any(
                    not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                    for value in probabilities
                )
                or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9)
            ):
                raise ValueError("HMM returned invalid state probabilities")
            alpha, beta = parameters[rate_rank]

            # Service capacity is sustainable system capacity, not spare
            # capacity at this instant. Using idle slots here made capacity
            # zero whenever the executor was busy and fed a self-reinforcing
            # rate collapse. idle_capacity remains a measured input for
            # diagnostics; total configured workers define gross capacity.
            service_capacity = (
                (1.0 - load)
                * self.service_rate_n
            )

            # Ls is the instantaneous number of tasks in the whole system.
            delta = (
                ls_tasks_in_system / (1.0 + ls_tasks_in_system)
                if ls_tasks_in_system > 0
                else 1.0
            )
            remaining_capacity = delta * service_capacity
            # Paper Eq. 12 is intentionally unnormalised.
            new_rate = alpha * self.rate + beta * remaining_capacity
            if not math.isfinite(new_rate):
                raise ValueError("Calculated token rate is not finite")

            clamp_reason = None
            if new_rate < self.min_rate:
                self.rate = self.min_rate
                clamp_reason = "minimum"
            elif new_rate > self.max_rate:
                self.rate = self.max_rate
                clamp_reason = "maximum"
            else:
                self.rate = new_rate

            return {
                "token_rate": self.rate,
                "rate_rank": rate_rank,
                "alpha": alpha,
                "beta": beta,
                "min_rate": self.min_rate,
                "max_rate": self.max_rate,
                "remaining_capacity": remaining_capacity,
                "service_capacity": service_capacity,
                "delta": delta,
                "state_probabilities": prediction["probabilities"],
                "updated": True,
                "proposed_rate": new_rate,
                "clamp_reason": clamp_reason,
                "skip_reason": None,
            }
