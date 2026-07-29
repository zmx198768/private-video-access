import hashlib
import time

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


def rate_limit(key, limit, period=60):
    bucket = int(time.time() // period)
    cache_key = f"chat-rate:{key}:{bucket}"
    if cache.add(cache_key, 1, timeout=period + 5):
        return False
    try:
        return cache.incr(cache_key) > limit
    except ValueError:
        cache.set(cache_key, 1, timeout=period + 5)
        return False


def code_fingerprint(code):
    return hashlib.sha256((code or "").encode()).hexdigest()[:16]


def serialize_message(message):
    participant = message.participant
    return {
        "id": message.id,
        "body": message.body,
        "created_at": timezone.localtime(message.created_at).isoformat(),
        "participant": {
            "id": str(participant.id) if participant else "",
            "display_name": participant.display_name if participant else "已离开访客",
            "masked_ip": participant.masked_ip if participant else "未知IP",
            "avatar_hue": participant.avatar_hue if participant else 0,
        },
    }


def entry_rate_limit(ip_address):
    return rate_limit(
        f"entry:{ip_address or 'unknown'}",
        settings.CHAT_ENTRY_RATE_PER_MINUTE,
    )


def send_rate_limit(participant_id):
    return rate_limit(
        f"send:{participant_id}",
        settings.CHAT_SEND_RATE_PER_MINUTE,
    )
