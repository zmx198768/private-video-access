import hashlib
import hmac
import ipaddress
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import update_session_auth_hash
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Prefetch
from django.core.paginator import Paginator
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    AccessCodeForm,
    CodeEntryForm,
    StyledPasswordChangeForm,
    SystemSettingsForm,
    VideoTitleForm,
    VideoUploadForm,
)
from .models import (
    AccessCode,
    AdminAuditLog,
    PlaybackSession,
    SecurityEvent,
    SystemSettings,
    Video,
    ViewEvent,
    digest_access_code,
)


def client_ip(request):
    value = request.META.get("REMOTE_ADDR")
    if settings.TRUST_PROXY_HEADERS:
        value = request.META.get("HTTP_X_REAL_IP") or value
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


def _code_fingerprint(code):
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def _rate_limited(ip):
    if not ip:
        return False
    key = f"code-attempt:{ip}:{int(time.time() // 60)}"
    try:
        return cache.incr(key) > 10
    except ValueError:
        cache.set(key, 1, timeout=90)
        return False


def _cookie_name(session_id):
    return f"pv_{str(session_id).replace('-', '')}"


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ok"})
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)


@never_cache
@require_GET
def fresh_csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


def _load_session(request, session_id, require_cookie=True):
    session = get_object_or_404(
        PlaybackSession.objects.select_related("access_code__video"),
        pk=session_id,
    )
    if require_cookie:
        token = request.COOKIES.get(_cookie_name(session.id))
        if not session.token_matches(token):
            raise Http404
    if not session.is_valid():
        raise Http404
    return session


@never_cache
@require_GET
def access_page(request):
    return render(request, "videos/access.html", {"form": CodeEntryForm()})


@never_cache
@require_POST
def authorize(request):
    ip = client_ip(request)
    form = CodeEntryForm(request.POST)
    if not form.is_valid():
        return render(request, "videos/access.html", {"form": form}, status=400)
    code = form.cleaned_data["code"]
    if _rate_limited(ip):
        SecurityEvent.objects.create(
            event_type="rate_limited", ip_address=ip, code_fingerprint=_code_fingerprint(code),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
        )
        return render(request, "videos/access.html", {"form": form, "error": "尝试次数过多，请稍后再试。"}, status=429)

    access_code = AccessCode.objects.select_related("video").filter(
        code_digest=digest_access_code(code),
        deleted_at__isnull=True,
    ).first()
    if not access_code or not access_code.valid_at() or not access_code.video.sharing_enabled or not access_code.video.is_ready:
        SecurityEvent.objects.create(
            event_type="invalid_code", ip_address=ip, code_fingerprint=_code_fingerprint(code),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
        )
        return render(request, "videos/access.html", {"form": form, "error": "授权码无效、未生效或已过期。"}, status=403)

    session, token = PlaybackSession.create_for(
        access_code, ip, request.META.get("HTTP_USER_AGENT", "")
    )
    ViewEvent.objects.create(session=session, event_type=ViewEvent.EventType.AUTHORIZED, ip_address=ip)
    response = redirect("videos:watch", session_id=session.id)
    response.set_cookie(
        _cookie_name(session.id),
        token,
        max_age=settings.PLAYBACK_SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="Lax",
        path=f"/",
    )
    return response


@never_cache
@ensure_csrf_cookie
@require_GET
def watch(request, session_id):
    try:
        session = _load_session(request, session_id)
    except Http404:
        return render(request, "videos/session_expired.html", status=403)
    return render(
        request,
        "videos/watch.html",
        {
            "playback_session": session,
            "video": session.access_code.video,
            "manifest_url": reverse("videos:manifest", args=[session.id]),
            "event_url": reverse("videos:playback_event", args=[session.id]),
        },
    )


def _stream_signature(session_id, filename, expires):
    payload = f"{session_id}|{filename}|{expires}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()


@never_cache
@require_GET
def manifest(request, session_id):
    session = _load_session(request, session_id)
    video = session.access_code.video
    path = (settings.VIDEO_HLS_DIR / video.hls_relative_path).resolve()
    root = settings.VIDEO_HLS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        raise Http404
    expires = int(time.time()) + settings.STREAM_URL_TTL
    output = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', stripped)
            if match:
                filename = Path(match.group(1)).name
                signature = _stream_signature(session.id, filename, expires)
                url = reverse("videos:stream_asset", args=[session.id, filename])
                signed_url = f"{url}?expires={expires}&sig={signature}"
                line = line.replace(match.group(1), signed_url)
            output.append(line)
            continue
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        filename = Path(stripped).name
        signature = _stream_signature(session.id, filename, expires)
        url = reverse("videos:stream_asset", args=[session.id, filename])
        output.append(f"{url}?expires={expires}&sig={signature}")
    response = HttpResponse("\n".join(output) + "\n", content_type="application/vnd.apple.mpegurl")
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@require_GET
def stream_asset(request, session_id, filename):
    session = _load_session(request, session_id, require_cookie=False)
    expires = request.GET.get("expires", "")
    supplied = request.GET.get("sig", "")
    try:
        if int(expires) < int(time.time()):
            raise ValueError
    except (ValueError, TypeError):
        return HttpResponseForbidden("链接已过期")
    expected = _stream_signature(session.id, filename, expires)
    if not hmac.compare_digest(expected, supplied):
        return HttpResponseForbidden("签名无效")

    safe_name = Path(filename).name
    if safe_name != filename or safe_name not in {"init.mp4", "index.m3u8"} and not safe_name.endswith(".m4s"):
        raise Http404
    video = session.access_code.video
    asset = (settings.VIDEO_HLS_DIR / str(video.id) / safe_name).resolve()
    video_dir = (settings.VIDEO_HLS_DIR / str(video.id)).resolve()
    if video_dir not in asset.parents or not asset.is_file():
        raise Http404

    response = HttpResponse()
    response["X-Accel-Redirect"] = f"/_protected_hls/{video.id}/{quote(safe_name)}"
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = "inline"
    return response


@require_POST
def playback_event(request, session_id):
    session = _load_session(request, session_id)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("无效请求")
    event_type = payload.get("event")
    allowed = {
        ViewEvent.EventType.START,
        ViewEvent.EventType.HEARTBEAT,
        ViewEvent.EventType.PAUSE,
        ViewEvent.EventType.SEEK,
        ViewEvent.EventType.ENDED,
    }
    if event_type not in allowed:
        return HttpResponseBadRequest("无效事件")
    try:
        position = max(0, min(int(float(payload.get("position", 0))), 24 * 3600))
    except (ValueError, TypeError):
        position = 0
    now = timezone.now()
    updates = {"last_seen_at": now, "max_position_seconds": max(session.max_position_seconds, position)}
    if event_type == ViewEvent.EventType.START and not session.started_at:
        updates["started_at"] = now
    if event_type == ViewEvent.EventType.HEARTBEAT:
        updates["watched_seconds"] = session.watched_seconds + 15
    if event_type == ViewEvent.EventType.ENDED:
        updates["ended_at"] = now
        updates["state"] = PlaybackSession.State.ENDED
    PlaybackSession.objects.filter(pk=session.pk).update(**updates)
    ViewEvent.objects.create(
        session=session, event_type=event_type, position_seconds=position, ip_address=client_ip(request)
    )
    return JsonResponse({"ok": True})


@staff_member_required
@require_GET
def manage_dashboard(request):
    visible_codes = AccessCode.objects.filter(deleted_at__isnull=True)
    videos = Video.objects.prefetch_related(Prefetch("access_codes", queryset=visible_codes))
    recent_sessions = PlaybackSession.objects.select_related("access_code__video")[:10]
    return render(
        request,
        "videos/manage.html",
        {
            "videos": videos,
            "recent_sessions": recent_sessions,
            "session_count": PlaybackSession.objects.count(),
        },
    )


@staff_member_required
@require_GET
def view_records(request):
    sessions = PlaybackSession.objects.select_related("access_code__video")
    paginator = Paginator(sessions, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    return render(
        request,
        "videos/records.html",
        {"page_obj": page_obj, "page_range": page_range},
    )


def _audit(request, action, target, detail=""):
    AdminAuditLog.objects.create(
        actor=request.user,
        action=action,
        target_type=target.__class__.__name__,
        target_id=str(target.pk),
        detail=detail,
        ip_address=client_ip(request),
    )


@staff_member_required
def manage_settings(request):
    settings_obj = SystemSettings.load()
    name_form = SystemSettingsForm(instance=settings_obj, prefix="identity")
    password_form = StyledPasswordChangeForm(request.user, prefix="password")

    if request.method == "POST" and request.POST.get("action") == "system_name":
        name_form = SystemSettingsForm(request.POST, instance=settings_obj, prefix="identity")
        if name_form.is_valid():
            old_name = settings_obj.system_name
            settings_obj = name_form.save(commit=False)
            settings_obj.updated_by = request.user
            settings_obj.save()
            _audit(request, "update_system_name", settings_obj, f"系统名称由“{old_name}”改为“{settings_obj.system_name}”")
            messages.success(request, "系统名称已更新。")
            return redirect("videos:settings")

    if request.method == "POST" and request.POST.get("action") == "password":
        password_form = StyledPasswordChangeForm(request.user, request.POST, prefix="password")
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            _audit(request, "change_admin_password", user, "管理员修改了自己的登录密码")
            messages.success(request, "管理员密码已修改，当前登录状态已保留。")
            return redirect("videos:settings")

    return render(
        request,
        "videos/settings.html",
        {
            "name_form": name_form,
            "password_form": password_form,
            "settings_obj": settings_obj,
        },
    )


@staff_member_required
def create_codes(request, video_id):
    video = get_object_or_404(Video, pk=video_id)
    form = AccessCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        issued = []
        try:
            with transaction.atomic():
                if form.cleaned_data["code_mode"] == "manual":
                    _, plain = AccessCode.issue_custom(
                        code=form.cleaned_data["custom_code"],
                        video=video,
                        starts_at=form.cleaned_data["starts_at"],
                        expires_at=form.cleaned_data["expires_at"],
                        note=form.cleaned_data["note"],
                        created_by=request.user,
                    )
                    issued.append(plain)
                else:
                    for _ in range(form.cleaned_data["quantity"]):
                        _, plain = AccessCode.issue(
                            video=video,
                            starts_at=form.cleaned_data["starts_at"],
                            expires_at=form.cleaned_data["expires_at"],
                            note=form.cleaned_data["note"],
                            created_by=request.user,
                        )
                        issued.append(plain)
                if not video.sharing_enabled:
                    video.sharing_enabled = True
                    video.save(update_fields=["sharing_enabled", "updated_at"])
        except ValueError as exc:
            form.add_error("custom_code", str(exc))
        else:
            mode = "手工设置" if form.cleaned_data["code_mode"] == "manual" else "自动生成"
            _audit(request, "create_access_codes", video, f"方式：{mode}；数量：{len(issued)}；已确保视频共享开启")
            return render(request, "videos/codes_issued.html", {"video": video, "codes": issued})
    return render(request, "videos/create_codes.html", {"video": video, "form": form})


@staff_member_required
def rename_video(request, video_id):
    video = get_object_or_404(Video, pk=video_id)
    form = VideoTitleForm(request.POST or None, initial={"title": video.title})
    if request.method == "POST" and form.is_valid():
        old_title = video.title
        video.title = form.cleaned_data["title"]
        video.save(update_fields=["title", "updated_at"])
        _audit(request, "rename_video", video, f"名称由“{old_title}”改为“{video.title}”")
        messages.success(request, f"视频名称已更新为“{video.title}”。")
        return redirect("videos:manage")
    return render(request, "videos/rename_video.html", {"video": video, "form": form})


def _probe_uploaded_mp4(path):
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    metadata = json.loads(probe.stdout)
    video_stream = next(
        (stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    format_name = metadata.get("format", {}).get("format_name", "")
    if not video_stream or not any(name in format_name.split(",") for name in ("mp4", "mov")):
        raise ValueError("文件不是包含有效视频轨道的 MP4")


@staff_member_required
def upload_video(request):
    form = VideoUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        source_root = settings.VIDEO_SOURCE_DIR.resolve()
        source_root.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex
        temporary_path = source_root / f".{file_id}.uploading"
        final_path = source_root / f"{file_id}.mp4"
        uploaded = form.cleaned_data["video_file"]
        try:
            with temporary_path.open("xb") as destination:
                for chunk in uploaded.chunks():
                    destination.write(chunk)
            _probe_uploaded_mp4(temporary_path)
            temporary_path.replace(final_path)
            stat = final_path.stat()
            video = Video.objects.create(
                title=form.cleaned_data["title"],
                source_key=hashlib.sha256(str(final_path).encode()).hexdigest(),
                source_path=str(final_path),
                source_size=stat.st_size,
                source_mtime_ns=stat.st_mtime_ns,
                stable_scan_count=1,
                processing_status=Video.ProcessingStatus.DISCOVERED,
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            form.add_error("video_file", f"视频校验或保存失败：{str(exc)[:180]}")
        else:
            _audit(
                request,
                "upload_video",
                video,
                f"原始文件名：{Path(uploaded.name).name[:240]}；保存文件名：{final_path.name}",
            )
            messages.success(request, f"“{video.title}”上传完成，系统将在一分钟内开始处理。")
            return redirect("videos:manage")
    return render(
        request,
        "videos/upload_video.html",
        {
            "form": form,
            "max_upload_gb": settings.MAX_VIDEO_UPLOAD_BYTES / (1024 ** 3),
        },
    )


@staff_member_required
@require_POST
def toggle_video_share(request, video_id):
    video = get_object_or_404(Video, pk=video_id)
    video.sharing_enabled = not video.sharing_enabled
    video.save(update_fields=["sharing_enabled", "updated_at"])
    _audit(request, "toggle_video_share", video, f"sharing_enabled={video.sharing_enabled}")
    messages.success(request, f"“{video.title}”已{'恢复' if video.sharing_enabled else '停止'}共享。")
    return redirect("videos:manage")


@staff_member_required
@require_POST
def delete_code(request, code_id):
    code = get_object_or_404(AccessCode, pk=code_id, deleted_at__isnull=True)
    now = timezone.now()
    with transaction.atomic():
        code.enabled = False
        code.deleted_at = now
        code.save(update_fields=["enabled", "deleted_at", "updated_at"])
        PlaybackSession.objects.filter(
            access_code=code,
            state=PlaybackSession.State.ACTIVE,
        ).update(state=PlaybackSession.State.REVOKED, ended_at=now)
    _audit(request, "delete_access_code", code, f"删除授权码 ****{code.code_hint}")
    messages.success(request, f"授权码 ****{code.code_hint} 已删除。")
    return redirect("videos:manage")
