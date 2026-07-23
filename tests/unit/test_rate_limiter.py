from __future__ import annotations

from vtv_schemas.rate_limit import RateLimitConfig, RateLimiter, TokenBucket

# --- RateLimitConfig defaults ---

def test_rate_limit_config_defaults():
    cfg = RateLimitConfig()
    assert cfg.requests_per_minute == 60
    assert cfg.burst == 10
    assert cfg.enabled is True


# --- TokenBucket initial state ---

def test_token_bucket_initial_state():
    bucket = TokenBucket(capacity=10, refill_rate=1.0)
    assert bucket.tokens == 10.0
    assert bucket.capacity == 10


# --- TokenBucket.consume() allows first request ---

def test_token_bucket_consume_allows_first():
    bucket = TokenBucket(capacity=5, refill_rate=1.0)
    assert bucket.consume() is True
    assert bucket.tokens == 4.0


# --- TokenBucket.consume() blocks when tokens=0 ---

def test_token_bucket_consume_blocks_when_empty():
    bucket = TokenBucket(capacity=1, refill_rate=0.0)
    assert bucket.consume() is True   # uses the 1 token
    assert bucket.consume() is False  # no tokens left, refill_rate=0


# --- RateLimiter.is_allowed() first request allowed ---

def test_rate_limiter_first_request_allowed():
    limiter = RateLimiter(RateLimitConfig(burst=5, requests_per_minute=60))
    assert limiter.is_allowed("ws-1") is True


# --- RateLimiter.is_allowed() exceeds burst → False ---

def test_rate_limiter_exceeds_burst():
    cfg = RateLimitConfig(burst=3, requests_per_minute=1, enabled=True)
    limiter = RateLimiter(cfg)
    # Drain all burst tokens
    for _ in range(3):
        assert limiter.is_allowed("ws-burst") is True
    # Next request should be denied (refill rate is tiny, no real time passes)
    assert limiter.is_allowed("ws-burst") is False


# --- RateLimiter.is_allowed() disabled config always True ---

def test_rate_limiter_disabled_always_allowed():
    cfg = RateLimitConfig(burst=1, requests_per_minute=1, enabled=False)
    limiter = RateLimiter(cfg)
    for _ in range(20):
        assert limiter.is_allowed("ws-disabled") is True


# --- RateLimiter.reset() clears bucket ---

def test_rate_limiter_reset_clears_bucket():
    cfg = RateLimitConfig(burst=1, requests_per_minute=1, enabled=True)
    limiter = RateLimiter(cfg)
    assert limiter.is_allowed("ws-reset") is True   # drains the 1 token
    assert limiter.is_allowed("ws-reset") is False  # bucket empty
    limiter.reset("ws-reset")
    # After reset a fresh bucket is created on next access
    assert limiter.is_allowed("ws-reset") is True
