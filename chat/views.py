import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from videos.ip_access import client_ip
from videos.models import AdminAuditLog

from .forms import ChatRoomForm
from .models import ChatMessage, ChatParticipant, ChatRoom
from .services import serialize_message

logger = logging.getLogger(__name__)


def _audit(request, action, target, detail=""):
    AdminAuditLog.objects.create(
        actor=request.user,
        action=action,
        target_type=target.__class__.__name__,
        target_id=str(target.pk),
        detail=detail,
        ip_address=client_ip(request),
    )


def _participant_cookie_name(participant_id):
    return f"chat_{str(participant_id).replace('-', '')}"


def _valid_participant(request, participant_id):
    participant = get_object_or_404(
        ChatParticipant.objects.select_related("room"),
        pk=participant_id,
    )
    token = request.COOKIES.get(_participant_cookie_name(participant.id))
    if not participant.token_matches(token) or not participant.is_valid(client_ip(request)):
        raise Http404
    return participant


def _notify_room(room, event_type):
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{room.id.hex}",
            {"type": event_type},
        )
    except Exception:
        logger.exception("Unable to notify chat room %s", room.id)


@require_GET
def entry(request):
    return redirect("videos:access")


@require_GET
def room(request, participant_id):
    participant = _valid_participant(request, participant_id)
    newest = list(
        ChatMessage.objects.filter(room=participant.room)
        .select_related("participant")
        .order_by("-id")[:50]
    )
    newest.reverse()
    participant.last_seen_at = timezone.now()
    participant.save(update_fields=["last_seen_at"])
    return render(
        request,
        "chat/room.html",
        {
            "participant": participant,
            "room": participant.room,
            "initial_messages": newest,
            "initial_count": len(newest),
            "message_max_length": settings.CHAT_MESSAGE_MAX_LENGTH,
            "history_url": reverse("chat:history", args=[participant.id]),
            "websocket_path": f"/ws/chat/{participant.id}/",
        },
    )


@require_POST
def leave_room(request, participant_id):
    participant = _valid_participant(request, participant_id)
    left_at = timezone.now()
    participant.revoked_at = left_at
    participant.last_seen_at = left_at
    participant.save(update_fields=["revoked_at", "last_seen_at"])
    response = redirect("videos:access")
    response.delete_cookie(
        participant.cookie_name,
        path="/",
        samesite="Lax",
    )
    return response


@require_GET
def history(request, participant_id):
    participant = _valid_participant(request, participant_id)
    queryset = ChatMessage.objects.filter(room=participant.room).select_related("participant")
    before = request.GET.get("before")
    after = request.GET.get("after")
    if before and after:
        return JsonResponse({"error": "游标参数冲突"}, status=400)
    try:
        if before:
            before_id = int(before)
            rows = list(queryset.filter(id__lt=before_id).order_by("-id")[:51])
            has_more = len(rows) > 50
            rows = rows[:50]
            rows.reverse()
        elif after:
            after_id = int(after)
            rows = list(queryset.filter(id__gt=after_id).order_by("id")[:100])
            has_more = queryset.filter(id__gt=rows[-1].id).exists() if len(rows) == 100 else False
        else:
            rows = list(queryset.order_by("-id")[:51])
            has_more = len(rows) > 50
            rows = rows[:50]
            rows.reverse()
    except (TypeError, ValueError):
        return JsonResponse({"error": "消息游标无效"}, status=400)
    participant.last_seen_at = timezone.now()
    participant.save(update_fields=["last_seen_at"])
    return JsonResponse(
        {
            "messages": [serialize_message(item) for item in rows],
            "has_more": has_more,
        }
    )


@staff_member_required
@require_GET
def manage_rooms(request):
    rooms = ChatRoom.objects.annotate(
        participant_count=Count("participants", distinct=True),
        message_count=Count("messages", distinct=True),
    ).order_by("-created_at")
    room_count = rooms.count()
    active_room_count = rooms.filter(is_active=True).count()
    paginator = Paginator(rooms, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    return render(
        request,
        "chat/manage.html",
        {
            "page_obj": page_obj,
            "page_range": page_range,
            "room_count": room_count,
            "active_room_count": active_room_count,
        },
    )


@staff_member_required
@require_GET
def participant_records(request):
    participants = (
        ChatParticipant.objects.select_related("room")
        .annotate(
            message_count=Count("messages"),
            last_spoke_at=Max("messages__created_at"),
        )
        .order_by("-joined_at")
    )
    selected_room = None
    room_id = request.GET.get("room")
    if room_id:
        selected_room = get_object_or_404(ChatRoom, pk=room_id)
        participants = participants.filter(room=selected_room)

    paginator = Paginator(participants, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    return render(
        request,
        "chat/participant_records.html",
        {
            "page_obj": page_obj,
            "page_range": page_range,
            "rooms": ChatRoom.objects.order_by("-created_at"),
            "selected_room": selected_room,
        },
    )


@staff_member_required
@require_GET
def message_records(request, room_id):
    room_obj = get_object_or_404(ChatRoom, pk=room_id)
    queryset = (
        ChatMessage.objects.filter(room=room_obj)
        .select_related("participant")
        .order_by("-created_at", "-id")
    )
    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    return render(
        request,
        "chat/message_records.html",
        {
            "room": room_obj,
            "page_obj": page_obj,
            "page_range": page_range,
        },
    )


@staff_member_required
def create_room(request):
    form = ChatRoomForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["custom_code"] if form.cleaned_data["code_mode"] == "manual" else None
        try:
            with transaction.atomic():
                room, plain = ChatRoom.create_with_code(
                    name=form.cleaned_data["name"],
                    code=code,
                    created_by=request.user,
                    nickname_group=(
                        None
                        if form.cleaned_data["nickname_group"] == "auto"
                        else form.cleaned_data["nickname_group"]
                    ),
                )
                _audit(request, "create_chat_room", room, f"创建聊天室，授权码尾号 ****{room.code_hint}")
        except ValueError as exc:
            form.add_error("custom_code", str(exc))
        else:
            return render(
                request,
                "chat/code_issued.html",
                {"room": room, "plain_code": plain, "action_label": "聊天室已创建"},
            )
    return render(request, "chat/create.html", {"form": form})


@staff_member_required
@require_POST
def toggle_room(request, room_id):
    room = get_object_or_404(ChatRoom, pk=room_id)
    with transaction.atomic():
        room.is_active = not room.is_active
        room.save(update_fields=["is_active", "updated_at"])
        if not room.is_active:
            room.participants.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        _audit(request, "toggle_chat_room", room, f"is_active={room.is_active}")
    if not room.is_active:
        _notify_room(room, "room.closed")
    messages.success(request, f"“{room.name}”已{'开放' if room.is_active else '关闭'}。")
    return redirect("chat:manage")


@staff_member_required
def rotate_code(request, room_id):
    room = get_object_or_404(ChatRoom, pk=room_id)
    form = ChatRoomForm(request.POST or None, room=room)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["custom_code"] if form.cleaned_data["code_mode"] == "manual" else None
        try:
            with transaction.atomic():
                plain = room.rotate_code(code)
                room.participants.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
                _audit(request, "rotate_chat_room_code", room, f"更换授权码，新尾号 ****{room.code_hint}")
        except ValueError as exc:
            form.add_error("custom_code", str(exc))
        else:
            _notify_room(room, "room.closed")
            return render(
                request,
                "chat/code_issued.html",
                {"room": room, "plain_code": plain, "action_label": "授权码已更换"},
            )
    return render(request, "chat/create.html", {"form": form, "room": room, "rotating": True})
