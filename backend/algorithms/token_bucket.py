
import time
import threading


class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        if rate <= 0 or capacity < 1:
            raise ValueError("Rate and capacity must be positive")

        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated_at = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.updated_at

        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.rate,
        )
        self.updated_at = now

    def acquire(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            with self.lock:
                self._refill()

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True

                wait_time = (1 - self.tokens) / self.rate

            time.sleep(min(wait_time, 0.02))

        return False
