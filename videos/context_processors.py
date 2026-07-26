from django.db import OperationalError, ProgrammingError

from .models import SystemSettings


def system_identity(request):
    try:
        system_name = SystemSettings.objects.values_list("system_name", flat=True).first()
    except (OperationalError, ProgrammingError):
        system_name = None
    return {"system_name": system_name or "私密视频授权播放系统"}
