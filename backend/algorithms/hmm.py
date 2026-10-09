
import numpy as np


class RateHMM:
    def __init__(self):
        self.initial = np.array([0.4, 0.3, 0.3])

        self.transition = np.array([
            [0.70, 0.30, 0.00],
            [0.15, 0.70, 0.15],
            [0.00, 0.30, 0.70],
        ])

        # Rows: LoadRank 0 through 4.
        # Columns: RateRank 1 through 3.
        self.emission = np.array([
            [0.750, 0.050, 0.005],
            [0.150, 0.200, 0.020],
            [0.075, 0.500, 0.075],
            [0.020, 0.200, 0.150],
            [0.005, 0.050, 0.750],
        ])

        # Normalize each emission row before using it
        # as a probability distribution.
        self.emission = (
            self.emission
            / self.emission.sum(axis=1, keepdims=True)
        )

        self.belief = self.initial.copy()

    def predict(self, load_rank):
        if load_rank not in range(5):
            raise ValueError("LoadRank must be between 0 and 4")

        predicted = self.belief @ self.transition

        posterior = (
            predicted * self.emission[load_rank]
        )

        total = posterior.sum()

        if total == 0:
            posterior = self.initial.copy()
        else:
            posterior = posterior / total

        self.belief = posterior

        state = int(np.argmax(posterior)) + 1

        return {
            "rate_rank": state,
            "probabilities": posterior.tolist(),
        }
