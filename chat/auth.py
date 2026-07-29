import ipaddress
from http.cookies import SimpleCookie

from django.conf import settings

from videos.ip_access import is_ip_blocked


def scope_client_ip(scope):
    value = None
    if settings.TRUST_PROXY_HEADERS:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw = headers.get(b"x-real-ip")
        if raw:
            value = raw.decode("ascii", errors="ignore")
    if not value and scope.get("client"):
        value = scope["client"][0]
    try:
        return str(ipaddress.ip_address(value))
    except (TypeError, ValueError):
        return None


def scope_cookie(scope, name):
    raw_cookie = ""
    for key, value in scope.get("headers", []):
        if key.lower() == b"cookie":
            raw_cookie = value.decode("latin1")
            break
    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(name)
    return morsel.value if morsel else None


def blocked_scope_ip(scope):
    ip_address = scope_client_ip(scope)
    return ip_address, is_ip_blocked(ip_address)
