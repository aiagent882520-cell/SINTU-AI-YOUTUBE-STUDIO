from app.security import RequestRateLimiter, client_address_allowed, same_origin_request


def test_client_ip_allowlist_supports_exact_addresses_and_cidrs():
    assert client_address_allowed("192.0.2.15", "")
    assert client_address_allowed("192.0.2.15", "192.0.2.15")
    assert client_address_allowed("192.0.2.15", "192.0.2.0/24,198.51.100.0/24")
    assert not client_address_allowed("192.0.3.15", "192.0.2.0/24")
    assert not client_address_allowed("not-an-ip", "192.0.2.0/24")
    assert not client_address_allowed("192.0.2.15", "not-a-network")


def test_same_origin_requires_matching_host_and_effective_port():
    assert same_origin_request("https://studio.example.test", "studio.example.test")
    assert same_origin_request("https://studio.example.test:443", "studio.example.test")
    assert same_origin_request("http://localhost:8000", "localhost:8000")
    assert not same_origin_request("https://evil.example.test", "studio.example.test")
    assert same_origin_request("http://studio.example.test", "studio.example.test")
    assert not same_origin_request("http://studio.example.test", "studio.example.test", "https")
    assert not same_origin_request("https://studio.example.test", "studio.example.test", "http")
    assert not same_origin_request("javascript:alert(1)", "studio.example.test")
    assert not same_origin_request("https://studio.example.test:444", "studio.example.test")


def test_request_rate_limiter_enforces_sliding_window_and_retry_time():
    limiter = RequestRateLimiter(max_clients=3)
    assert limiter.check("client-a", 2, 10, now=100) == (True, 0)
    assert limiter.check("client-a", 2, 10, now=101) == (True, 0)
    allowed, retry_after = limiter.check("client-a", 2, 10, now=102)
    assert allowed is False
    assert retry_after == 8
    assert limiter.check("client-a", 2, 10, now=111) == (True, 0)


def test_request_rate_limiter_bounds_client_state_and_can_reset():
    limiter = RequestRateLimiter(max_clients=2)
    limiter.check("one", 5, 60, now=1)
    limiter.check("two", 5, 60, now=1)
    limiter.check("three", 5, 60, now=1)
    assert len(limiter._events) <= 2
    limiter.reset("three")
    assert "three" not in limiter._events
    limiter.reset()
    assert len(limiter._events) == 0
