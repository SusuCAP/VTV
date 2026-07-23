from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    burst: int = 10  # allow short bursts above RPM
    enabled: bool = True


@dataclass
class TokenBucket:
    """Token bucket rate limiter for a single key (workspace_id)."""

    capacity: int
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def consume(self, count: int = 1) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False


class RateLimiter:
    """Per-workspace rate limiter using token buckets."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                capacity=self._config.burst,
                refill_rate=self._config.requests_per_minute / 60.0,
            )
        )

    def is_allowed(self, workspace_id: str) -> bool:
        if not self._config.enabled:
            return True
        return self._buckets[workspace_id].consume()

    def reset(self, workspace_id: str) -> None:
        self._buckets.pop(workspace_id, None)
