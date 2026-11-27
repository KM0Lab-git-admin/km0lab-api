"""Who a request is counted against (``app/ratelimit.py``).

Behind Railway every connection comes from its proxy: counted by connection,
all residents share one quota of login codes.
"""

from starlette.requests import Request

from app.ratelimit import client_ip, rate_limit_key

PROXY = "100.64.0.3"  # Railway's hop: the same for everyone


def _request(real_ip: str | None = None, forwarded: str | None = None) -> Request:
    headers = []
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode()))
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request({"type": "http", "headers": headers, "client": (PROXY, 1)})


def test_two_residents_behind_the_proxy_do_not_share_a_quota():
    anna = _request(real_ip="81.0.0.10")
    pol = _request(real_ip="81.0.0.11")
    assert rate_limit_key(anna) == "81.0.0.10"
    assert rate_limit_key(pol) == "81.0.0.11"
    assert rate_limit_key(anna) != rate_limit_key(pol)


def test_without_the_header_it_is_the_connection():
    assert client_ip(_request()) == PROXY
    assert client_ip(_request(real_ip="  ")) == PROXY


def test_only_an_address_is_accepted():
    assert client_ip(_request(real_ip="not-an-ip")) == PROXY
    assert client_ip(_request(real_ip="81.0.0.10, 10.0.0.1")) == PROXY
    assert client_ip(_request(real_ip="2001:DB8::1")) == "2001:db8::1"


def test_x_forwarded_for_is_not_trusted():
    """A client can put anything in it; Railway only vouches for X-Real-IP."""
    assert client_ip(_request(forwarded="203.0.113.7")) == PROXY
    assert (
        client_ip(_request(real_ip="81.0.0.10", forwarded="203.0.113.7"))
        == "81.0.0.10"
    )
