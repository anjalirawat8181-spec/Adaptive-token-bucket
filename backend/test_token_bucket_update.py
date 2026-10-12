
from algorithms.token_bucket import TokenBucket

bucket = TokenBucket(rate=10, capacity=5)

print("Initial rate:", bucket.rate)
assert bucket.rate == 10

bucket.set_rate(20)
print("Updated rate:", bucket.rate)
assert bucket.rate == 20

assert bucket.acquire(timeout=1) is True
print("Token acquisition: successful")

try:
    bucket.set_rate(0)
    raise AssertionError("Invalid rate was accepted")
except ValueError:
    print("Invalid rate correctly rejected")

print("\nALL TESTS PASSED!")
