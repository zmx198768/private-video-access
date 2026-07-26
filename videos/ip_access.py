import ipaddress
import re
from functools import lru_cache

from django.conf import settings

MAX_IP_BLACKLIST_RULES = 100
MAX_IP_BLACKLIST_RULE_LENGTH = 200


def client_ip(request):
    value = request.META.get("REMOTE_ADDR")
    if settings.TRUST_PROXY_HEADERS:
        value = request.META.get("HTTP_X_REAL_IP") or value
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


def normalize_ip_blacklist(value):
    rules = []
    for line_number, raw_rule in enumerate((value or "").splitlines(), start=1):
        rule = raw_rule.strip()
        if not rule:
            continue
        if len(rule) > MAX_IP_BLACKLIST_RULE_LENGTH:
            raise ValueError(f"第{line_number}行超过{MAX_IP_BLACKLIST_RULE_LENGTH}个字符")
        try:
            re.compile(rule)
        except re.error as exc:
            raise ValueError(f"第{line_number}行正则表达式无效：{exc}") from exc
        rules.append(rule)
    if len(rules) > MAX_IP_BLACKLIST_RULES:
        raise ValueError(f"最多允许{MAX_IP_BLACKLIST_RULES}条IP黑名单规则")
    return "\n".join(rules)


@lru_cache(maxsize=32)
def _compiled_ip_blacklist(value):
    return tuple(re.compile(rule) for rule in value.splitlines() if rule)


def is_ip_blocked(ip, blacklist=None):
    if not ip:
        return False
    if blacklist is None:
        from .models import SystemSettings

        blacklist = SystemSettings.objects.values_list("ip_blacklist", flat=True).first() or ""
    return any(pattern.fullmatch(ip) for pattern in _compiled_ip_blacklist(blacklist))
