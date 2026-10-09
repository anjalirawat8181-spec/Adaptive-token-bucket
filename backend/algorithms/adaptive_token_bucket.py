
from algorithms.hmm import RateHMM


class AdaptiveRateController:
    def __init__(
        self,
        initial_rate,
        max_threads,
        task_cost_ms,
    ):
        self.rate = float(initial_rate)
        self.max_threads = max_threads
        self.task_cost_ms = task_cost_ms
        self.hmm = RateHMM()

    def update(self, load, load_rank, mean_tasks, idle_capacity):
        prediction = self.hmm.predict(load_rank)
        rate_rank = prediction["rate_rank"]

        parameters = {
            1: (1.0, 1.0),
            2: (0.5, 1.0),
            3: (0.0, 0.8),
        }

        alpha, beta = parameters[rate_rank]

        min_rate = 1000 / self.task_cost_ms
        max_rate = (
            self.max_threads * 1000 / self.task_cost_ms
        )

        service_capacity = max(
            0.0,
            (1.0 - load) * idle_capacity,
        )

        # Queueing-model adjustment factor.
        delta = (
            mean_tasks / (1.0 + mean_tasks)
            if mean_tasks > 0
            else 1.0
        )

        remaining_capacity = delta * service_capacity

        new_rate = (
            alpha * self.rate
            + beta * remaining_capacity
        )

        self.rate = max(
            min(new_rate, max_rate),
            min_rate,
        )

        return {
            "token_rate": self.rate,
            "rate_rank": rate_rank,
            "alpha": alpha,
            "beta": beta,
            "min_rate": min_rate,
            "max_rate": max_rate,
            "remaining_capacity": remaining_capacity,
            "state_probabilities": prediction["probabilities"],
        }
