
from algorithms.load_calculator import calculate_load, load_rank

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
