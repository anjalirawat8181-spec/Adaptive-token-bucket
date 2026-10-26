
import math
import time
import threading


class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Rate must be positive and finite")
        if not math.isfinite(capacity) or capacity < 1:
            raise ValueError("Capacity must be positive and finite")

        self.rate = float(rate)
        self.capacity = float(capacity)
        self.tokens = self.capacity
        self.updated_at = time.monotonic()
        self.lock = threading.Condition()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.updated_at

        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.rate,
        )
        self.updated_at = now

    def set_rate(self, new_rate: float):
        """Safely change the token fill rate."""
        if not math.isfinite(new_rate) or new_rate <= 0:
            raise ValueError("Rate must be positive and finite")

        with self.lock:
            self._refill()
            self.rate = float(new_rate)
            self.lock.notify_all()

    def acquire(self, timeout: float = 5.0) -> bool:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Timeout must be finite and non-negative")
        deadline = time.monotonic() + timeout

        while True:
            with self.lock:
                self._refill()

                if self.tokens >= 1:
                    if timeout > 0 and time.monotonic() > deadline:
                        return False
                    self.tokens -= 1
                    return True

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_time = (1 - self.tokens) / self.rate

                self.lock.wait(timeout=min(wait_time, remaining))
