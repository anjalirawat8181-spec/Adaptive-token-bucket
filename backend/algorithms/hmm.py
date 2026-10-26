
import math
from collections import deque
from numbers import Integral

import numpy as np


HMM_WINDOW = 20


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

        self.belief = self.initial.copy()
        self.observations = deque(maxlen=HMM_WINDOW)

    def _forward_belief(self, observations):
        belief = self.initial.copy()
        for observation in observations:
            belief = (belief @ self.transition) * self.emission[observation]
            total = belief.sum()
            if not np.all(np.isfinite(belief)) or total <= 0 or not math.isfinite(total):
                raise ValueError("HMM produced invalid state probabilities")
            belief /= total
        return belief

    def _viterbi_state(self, observations):
        log_transition = np.full_like(self.transition, -np.inf, dtype=float)
        positive_transition = self.transition > 0
        log_transition[positive_transition] = np.log(
            self.transition[positive_transition]
        )
        log_emission = np.log(self.emission)
        scores = np.log(self.initial) + log_emission[observations[0]]
        backpointers = []
        for observation in observations[1:]:
            candidates = scores[:, None] + log_transition
            backpointers.append(np.argmax(candidates, axis=0))
            scores = np.max(candidates, axis=0) + log_emission[observation]

        state = int(np.argmax(scores))
        for previous in reversed(backpointers):
            state = int(previous[state])
        return state

    def predict(self, load_rank):
        if not isinstance(load_rank, Integral) or load_rank not in range(5):
            raise ValueError("LoadRank must be between 0 and 4")

        self.observations.append(int(load_rank))
        observation_window = list(self.observations)
        posterior = self._forward_belief(observation_window)
        decoded_state = self._viterbi_state(observation_window)
        predicted = self.transition[decoded_state]
        best_probability = float(np.max(predicted))
        best_states = np.flatnonzero(
            np.isclose(predicted, best_probability, rtol=1e-12, atol=1e-12)
        )
        state_index = (
            decoded_state
            if decoded_state in best_states
            else int(best_states[0])
        )
        state = state_index + 1
        self.belief = posterior

        if not 1 <= state <= 3:
            raise ValueError("HMM produced an invalid rate rank")

        return {
            "rate_rank": state,
            "probabilities": posterior.tolist(),
            "decoded_state": decoded_state + 1,
        }
