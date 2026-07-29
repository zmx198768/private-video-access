import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .auth import blocked_scope_ip, scope_cookie
from .models import ChatMessage, ChatParticipant
from .services import send_rate_limit, serialize_message


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.participant_id = self.scope["url_route"]["kwargs"]["participant_id"]
        self.ip_address, blocked = await database_sync_to_async(blocked_scope_ip)(self.scope)
        if blocked:
            await self.close(code=4403)
            return
        cookie_name = f"chat_{str(self.participant_id).replace('-', '')}"
        token = scope_cookie(self.scope, cookie_name)
        participant = await self._get_participant(token)
        if not participant:
            await self.close(code=4403)
            return
        self.room_id = participant.room_id
        self.group_name = f"chat_{self.room_id.hex}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connected", "participant_id": str(self.participant_id)})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") != "message":
            await self.send_json({"type": "error", "message": "不支持的消息类型"})
            return
        body = str(content.get("body", "")).strip()
        if not body:
            await self.send_json({"type": "error", "message": "消息不能为空"})
            return
        if len(body) > settings.CHAT_MESSAGE_MAX_LENGTH:
            await self.send_json(
                {"type": "error", "message": f"消息不能超过{settings.CHAT_MESSAGE_MAX_LENGTH}个字符"}
            )
            return
        try:
            client_nonce = uuid.UUID(str(content.get("client_nonce", "")))
        except (ValueError, TypeError, AttributeError):
            await self.send_json({"type": "error", "message": "消息编号无效"})
            return
        limited = await database_sync_to_async(send_rate_limit)(self.participant_id)
        if limited:
            await self.send_json({"type": "error", "message": "发送过于频繁，请稍后再试"})
            return
        message = await self._save_message(body, client_nonce)
        if not message:
            await self.send_json({"type": "error", "message": "聊天室已关闭或会话已失效"})
            await self.close(code=4403)
            return
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat.message", "message": serialize_message(message)},
        )

    async def chat_message(self, event):
        await self.send_json({"type": "message", "message": event["message"]})

    async def room_closed(self, event):
        await self.send_json({"type": "room_closed", "message": "聊天室已关闭或授权码已更换"})
        await self.close(code=4403)

    @database_sync_to_async
    def _get_participant(self, token):
        participant = (
            ChatParticipant.objects.select_related("room")
            .filter(pk=self.participant_id)
            .first()
        )
        if not participant:
            return None
        if not participant.token_matches(token) or not participant.is_valid(self.ip_address):
            return None
        participant.last_seen_at = timezone.now()
        participant.save(update_fields=["last_seen_at"])
        return participant

    @database_sync_to_async
    def _save_message(self, body, client_nonce):
        participant = (
            ChatParticipant.objects.select_related("room")
            .filter(pk=self.participant_id)
            .first()
        )
        if not participant or not participant.is_valid(self.ip_address):
            return None
        try:
            with transaction.atomic():
                message = ChatMessage.objects.create(
                    room_id=participant.room_id,
                    participant=participant,
                    body=body,
                    client_nonce=client_nonce,
                )
                participant.last_seen_at = timezone.now()
                participant.save(update_fields=["last_seen_at"])
                participant.room.last_message_at = message.created_at
                participant.room.save(update_fields=["last_message_at", "updated_at"])
        except IntegrityError:
            message = ChatMessage.objects.select_related("participant").get(
                participant=participant,
                client_nonce=client_nonce,
            )
        return ChatMessage.objects.select_related("participant").get(pk=message.pk)
