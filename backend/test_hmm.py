
import unittest

import numpy as np

from algorithms.hmm import HMM_WINDOW, RateHMM

class RateHMMTests(unittest.TestCase):
    def test_paper_emission_columns_sum_to_one(self):
        hmm = RateHMM()
        np.testing.assert_allclose(hmm.emission.sum(axis=0), 1.0, atol=1e-9)

    def test_all_low_and_high_observation_paths_decode_expected_states(self):
        low = RateHMM()
        high = RateHMM()
        low_result = None
        high_result = None
        for _ in range(HMM_WINDOW):
            low_result = low.predict(0)
            high_result = high.predict(4)
        self.assertEqual(low_result["decoded_state"], 1)
        self.assertEqual(low_result["rate_rank"], 1)
        self.assertEqual(high_result["decoded_state"], 3)
        self.assertEqual(high_result["rate_rank"], 3)

    def test_window_is_bounded_and_probabilities_are_forward_belief(self):
        hmm = RateHMM()
        results = [hmm.predict(rank) for rank in (0, 4) * 20]
        self.assertEqual(len(hmm.observations), HMM_WINDOW)
        self.assertAlmostEqual(sum(results[-1]["probabilities"]), 1.0)

    def test_prediction_tie_prefers_the_viterbi_decoded_state(self):
        hmm = RateHMM()
        hmm.transition[0] = [0.4, 0.4, 0.2]
        result = hmm.predict(0)
        self.assertEqual(result["decoded_state"], 1)
        self.assertEqual(result["rate_rank"], 1)


if __name__ == "__main__":
    unittest.main()
