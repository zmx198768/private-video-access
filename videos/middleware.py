import logging

from django.core.cache import cache
from django.http import HttpResponseForbidden

from .ip_access import client_ip, is_ip_blocked

logger = logging.getLogger(__name__)


class IPBlacklistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = client_ip(request)
        if is_ip_blocked(ip):
            self._record_block(ip, request.META.get("HTTP_USER_AGENT", ""))
            return HttpResponseForbidden(
                "该IP已被禁止访问。",
                content_type="text/plain; charset=utf-8",
            )
        return self.get_response(request)

    @staticmethod
    def _record_block(ip, user_agent):
        try:
            event_key = f"ip-blacklist-event:{ip}"
            if cache.add(event_key, 1, timeout=60):
                from .models import SecurityEvent

                SecurityEvent.objects.create(
                    event_type="ip_blacklisted",
                    ip_address=ip,
                    user_agent=user_agent[:2000],
                    detail="请求被IP黑名单拒绝",
                )
        except Exception:
            logger.exception("Unable to record blocked IP request")
