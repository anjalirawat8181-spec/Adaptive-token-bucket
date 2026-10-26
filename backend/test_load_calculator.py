
import unittest

from algorithms.load_calculator import calculate_load, load_rank


class LoadWeightTests(unittest.TestCase):
    def test_paper_weight_cases(self):
        cases = (
            ((0.8, 0.6, 0.2), [0.90, 0.07, 0.03]),
            ((0.9, 0.8, 0.2), [0.50, 0.47, 0.03]),
            ((0.7, 0.6, 0.2), [0.50, 0.40, 0.10]),
            ((0.6, 0.2, 0.1), [0.70, 0.20, 0.10]),
        )
        for indicators, expected in cases:
            with self.subTest(indicators=indicators):
                for actual, weight in zip(
                    calculate_load(*indicators)["weights"], expected
                ):
                    self.assertAlmostEqual(actual, weight, places=9)

    def test_all_same_interval_uses_case_one_weights(self):
        for indicators in ((0.1, 0.2, 0.3), (0.55, 0.6, 0.7), (0.8, 0.9, 1.0)):
            with self.subTest(indicators=indicators):
                for actual, weight in zip(
                    calculate_load(*indicators)["weights"],
                    [0.50, 0.30, 0.20],
                ):
                    self.assertAlmostEqual(actual, weight, places=9)

    def test_unavailable_indicators_are_renormalized_by_default(self):
        normalized = calculate_load(cpu=None, memory=0.5, resources=0.25)
        unnormalized = calculate_load(
            cpu=None,
            memory=0.5,
            resources=0.25,
            renormalize_unavailable=False,
        )
        self.assertAlmostEqual(sum(normalized["weights"]), 1.0)
        self.assertAlmostEqual(unnormalized["load"], 0.4)

# Test 1: Calculate overall load
result = calculate_load(
    cpu=0.70,
    memory=0.55,
    resources=0.50,
)

load = result["load"]
rank = load_rank(load)

print("Test 1: Load calculation")
print(f"Overall Load: {load:.3f}")
print(f"LoadRank: {rank}")
print(f"Weights: {result['weights']}")

# Validate the calculated values
assert 0 <= load <= 1, "Load is out of range!"
assert rank in range(5), "Invalid LoadRank!"

# Test 2: Check all five LoadRank categories
test_cases = [
    (0.20, 0),
    (0.40, 1),
    (0.60, 2),
    (0.80, 3),
    (0.95, 4),
]

print("\nTest 2: LoadRank classification")

for value, expected_rank in test_cases:
    actual_rank = load_rank(value)
    print(f"Load={value:.2f}, Rank={actual_rank}")
    assert actual_rank == expected_rank, (
        f"Expected {expected_rank}, got {actual_rank}"
    )

# Test 3: Invalid input should be rejected
try:
    calculate_load(cpu=1.2, memory=0.5, resources=0.5)
    raise AssertionError("Invalid CPU value was accepted!")
except ValueError:
    print("\nInvalid input correctly rejected.")

print("\nALL TESTS PASSED!")
