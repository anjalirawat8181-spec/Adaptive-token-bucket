
from algorithms.token_bucket import TokenBucket

bucket = TokenBucket(rate=10, capacity=5)

for i in range(8):
    accepted = bucket.acquire(timeout=2)
    print(f"Request {i + 1}: {accepted}")
