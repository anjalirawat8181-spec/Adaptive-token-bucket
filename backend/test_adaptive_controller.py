import math
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from algorithms.adaptive_token_bucket import AdaptiveRateController
from algorithms.token_bucket import TokenBucket


class TokenBucketTests(unittest.TestCase):
    def test_refill_respects_elapsed_time_and_capacity(self):
        with patch(
            "algorithms.token_bucket.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 0.5],
        ):
            bucket = TokenBucket(rate=2.0, capacity=1)
            self.assertTrue(bucket.acquire(timeout=0))
            self.assertEqual(bucket.tokens, 0.0)
            bucket._refill()

        self.assertEqual(bucket.tokens, 1.0)

    def test_initial_burst_is_limited_by_capacity(self):
        bucket = TokenBucket(rate=1.0, capacity=3)
        self.assertEqual(
            [bucket.acquire(timeout=0) for _ in range(4)],
            [True, True, True, False],
        )
        self.assertEqual(bucket.tokens, 0.0)

    def test_acquire_fails_if_token_refills_after_its_deadline(self):
        bucket = TokenBucket(rate=1.0, capacity=1)
        with patch(
            "algorithms.token_bucket.time.monotonic",
            return_value=0.0,
        ):
            bucket.updated_at = 0.0
            self.assertTrue(bucket.acquire(timeout=0))
        with (
            patch(
                "algorithms.token_bucket.time.monotonic",
                side_effect=[0.0, 0.0, 0.0, 2.0, 2.0],
            ),
            patch.object(threading.Condition, "wait", return_value=None),
        ):
            self.assertFalse(bucket.acquire(timeout=1.0))

    def test_concurrent_acquisition_keeps_bucket_state_bounded(self):
        bucket = TokenBucket(rate=1000.0, capacity=4)
        with ThreadPoolExecutor(max_workers=16) as pool:
            accepted = list(pool.map(
                lambda _: bucket.acquire(timeout=2.0),
                range(32),
            ))

        self.assertTrue(all(accepted))
        self.assertGreaterEqual(bucket.tokens, 0.0)
        self.assertLessEqual(bucket.tokens, bucket.capacity)

    def test_invalid_rates_capacity_and_timeout_are_rejected(self):
        for rate in (0, -1, float("nan"), float("inf")):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                TokenBucket(rate=rate, capacity=1)
        for capacity in (0, -1, float("nan"), float("inf")):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                TokenBucket(rate=1, capacity=capacity)

        bucket = TokenBucket(rate=1, capacity=1)
        for timeout in (-1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                bucket.acquire(timeout=timeout)

    def test_rate_change_wakes_a_waiting_acquirer(self):
        bucket = TokenBucket(rate=0.01, capacity=1)
        self.assertTrue(bucket.acquire(timeout=0))
        acquired = []
        entered_wait = threading.Event()
        original_wait = threading.Condition.wait

        def observed_wait(condition, timeout=None):
            entered_wait.set()
            return original_wait(condition, timeout)

        waiter = threading.Thread(
            target=lambda: acquired.append(bucket.acquire(timeout=1.0))
        )
        with patch.object(threading.Condition, "wait", observed_wait):
            waiter.start()
            self.assertTrue(entered_wait.wait(timeout=1.0))
            bucket.set_rate(1000.0)
            waiter.join(timeout=0.5)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(acquired, [True])


class AdaptiveRateControllerTests(unittest.TestCase):
    def test_rate_adapts_to_load_with_consistent_units_and_bounds(self):
        controller = AdaptiveRateController(
            initial_rate=100,
            max_threads=8,
            task_cost_ms=20,
        )
        initial = controller.rate
        with patch.object(
            controller.hmm,
            "predict",
            side_effect=[
                {"rate_rank": 1, "probabilities": [1, 0, 0]},
                {"rate_rank": 3, "probabilities": [0, 0, 1]},
            ],
        ):
            low_load = controller.update(
                load=0.1,
                load_rank=0,
                ls_tasks_in_system=1.0,
                idle_capacity=8,
            )
            high_load = controller.update(
                load=1.0,
                load_rank=4,
                ls_tasks_in_system=1.0,
                idle_capacity=8,
            )
        self.assertGreater(low_load["token_rate"], initial)
        self.assertLessEqual(low_load["token_rate"], 400.0)
        self.assertLess(high_load["token_rate"], low_load["token_rate"])
        self.assertGreaterEqual(high_load["token_rate"], 50.0)
        self.assertLessEqual(high_load["token_rate"], 400.0)
        self.assertTrue(math.isfinite(high_load["token_rate"]))

    def test_missing_load_does_not_update_hmm_or_rate(self):
        controller = AdaptiveRateController(50, 8, 20)
        initial_belief = controller.hmm.belief.copy()

        result = controller.update(
            load=None,
            load_rank=None,
            mean_tasks=0.0,
            idle_capacity=8,
        )

        self.assertFalse(result["updated"])
        self.assertEqual(result["token_rate"], 50.0)
        self.assertTrue((controller.hmm.belief == initial_belief).all())

    def test_zero_available_worker_slots_is_a_valid_zero_capacity_signal(self):
        controller = AdaptiveRateController(50, 8, 20)
        result = controller.update(
            load=0.8,
            load_rank=4,
            mean_tasks=1.0,
            idle_capacity=0,
        )
        self.assertAlmostEqual(result["service_capacity"], 80.0)
        self.assertGreater(result["remaining_capacity"], 0.0)
        self.assertGreaterEqual(result["token_rate"], controller.min_rate)
        self.assertLessEqual(result["token_rate"], controller.max_rate)

    def test_high_load_clamps_at_minimum_and_reports_reason(self):
        controller = AdaptiveRateController(50, 8, 20)
        result = controller.update(
            load=1.0,
            load_rank=4,
            mean_tasks=8.0,
            idle_capacity=0,
        )
        self.assertEqual(result["token_rate"], controller.min_rate)
        self.assertEqual(result["clamp_reason"], "minimum")

    def test_constant_load_has_bounded_stable_rate_and_never_exceeds_max(self):
        controller = AdaptiveRateController(50, 8, 20)
        rates = [
            controller.update(0.25, 1, 4.0, 0)["token_rate"]
            for _ in range(100)
        ]
        self.assertTrue(all(
            controller.min_rate <= rate <= controller.max_rate
            for rate in rates
        ))
        self.assertAlmostEqual(rates[-1], rates[-2], places=5)

    def test_paper_eq12_uses_unnormalised_rank_weights_and_minimum(self):
        controller = AdaptiveRateController(50, 8, 20)
        self.assertEqual(controller.min_rate, 50.0)
        cases = ((1, 150.0), (2, 175.0), (3, 80.0))
        for rate_rank, expected in cases:
            prediction = {"rate_rank": rate_rank, "probabilities": [1, 0, 0]}
            with patch.object(controller.hmm, "predict", return_value=prediction):
                result = controller.update(
                    load=0.5,
                    load_rank=2,
                    ls_tasks_in_system=1.0,
                    idle_capacity=0,
                )
            self.assertAlmostEqual(result["token_rate"], expected)

    def test_system_task_count_is_not_divided_by_worker_count(self):
        controller = AdaptiveRateController(50, 8, 20)
        prediction = {"rate_rank": 3, "probabilities": [0, 0, 1]}
        with patch.object(controller.hmm, "predict", return_value=prediction):
            result = controller.update(
                load=0.5,
                load_rank=2,
                ls_tasks_in_system=7.0,
                idle_capacity=0,
            )
        self.assertAlmostEqual(result["delta"], 7 / 8)
        self.assertAlmostEqual(result["remaining_capacity"], 175.0)
        self.assertAlmostEqual(result["token_rate"], 140.0)

    def test_hmm_probabilities_are_normalized_for_every_load_rank(self):
        controller = AdaptiveRateController(50, 8, 20)
        for load_rank in range(5):
            result = controller.update(
                load=load_rank / 4,
                load_rank=load_rank,
                mean_tasks=0,
                idle_capacity=8,
            )
            probabilities = result["state_probabilities"]
            self.assertIn(result["rate_rank"], {1, 2, 3})
            self.assertAlmostEqual(sum(probabilities), 1.0)
            self.assertTrue(all(
                math.isfinite(value) and value >= 0
                for value in probabilities
            ))

    def test_invalid_hmm_rank_or_probabilities_are_rejected(self):
        controller = AdaptiveRateController(50, 8, 20)
        for prediction in (
            {"rate_rank": 4, "probabilities": [0.0, 0.0, 1.0]},
            {"rate_rank": 3, "probabilities": [0.2, 0.2, 0.2]},
            {"rate_rank": 3, "probabilities": [0.1, float("nan"), 0.9]},
        ):
            with (
                patch.object(controller.hmm, "predict", return_value=prediction),
                self.assertRaises(ValueError),
            ):
                controller.update(0.5, 2, 1.0, 4)

    def test_invalid_configuration_and_measurements_are_rejected(self):
        for arguments in (
            (0, 8, 20),
            (50, 0, 20),
            (50, 8, 0),
            (float("nan"), 8, 20),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                AdaptiveRateController(*arguments)

        controller = AdaptiveRateController(50, 8, 20)
        with self.assertRaises(ValueError):
            controller.update(1.1, 4, 1, 8)
        with self.assertRaises(ValueError):
            controller.update(0.5, 2, -1, 8)
        with self.assertRaises(ValueError):
            controller.update(0.5, 2, 1, 9)

    def test_concurrent_updates_keep_rate_finite_and_bounded(self):
        controller = AdaptiveRateController(50, 8, 20)
        inputs = [
            (index % 5 / 4, index % 5, index / 10, 8)
            for index in range(40)
        ]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda values: controller.update(*values),
                inputs,
            ))

        self.assertTrue(all(math.isfinite(row["token_rate"]) for row in results))
        self.assertTrue(all(
            50.0 <= row["token_rate"] <= 400.0 for row in results
        ))


if __name__ == "__main__":
    unittest.main()
