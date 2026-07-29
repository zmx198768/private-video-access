import hashlib
import hmac
import secrets
import uuid

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from videos.models import CODE_ALPHABET, digest_access_code, normalize_access_code

from .nicknames import default_nickname_group, nickname_for, nickname_group_title


class ChatRoom(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("聊天室名称", max_length=120)
    code_digest = models.CharField("授权码摘要", max_length=64, unique=True, db_index=True)
    code_hint = models.CharField("授权码尾号", max_length=4)
    nickname_group = models.CharField("备用昵称组", max_length=40, default=default_nickname_group)
    is_active = models.BooleanField("开放", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="创建人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    last_message_at = models.DateTimeField("最后消息时间", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "聊天室"
        verbose_name_plural = "聊天室"

    def __str__(self):
        return self.name

    @classmethod
    def create_with_code(cls, *, name, code=None, created_by=None, nickname_group=None):
        from videos.code_registry import code_digest_in_use

        nickname_group = nickname_group or default_nickname_group()
        if code:
            plain = normalize_access_code(code)
            if len(plain) != 10:
                raise ValueError("聊天室授权码必须为10位英文字母或数字")
            digest = digest_access_code(plain)
            if code_digest_in_use(digest):
                raise ValueError("该授权码已被其他内容使用，请更换一个")
            return cls.objects.create(
                name=name,
                code_digest=digest,
                code_hint=plain[-4:],
                nickname_group=nickname_group,
                created_by=created_by,
            ), plain

        for _ in range(20):
            plain = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
            digest = digest_access_code(plain)
            if code_digest_in_use(digest):
                continue
            try:
                with transaction.atomic():
                    room = cls.objects.create(
                        name=name,
                        code_digest=digest,
                        code_hint=plain[-4:],
                        nickname_group=nickname_group,
                        created_by=created_by,
                    )
                return room, plain
            except IntegrityError:
                continue
        raise RuntimeError("无法生成唯一的聊天室授权码")

    @property
    def nickname_group_label(self):
        return nickname_group_title(self.nickname_group)

    def rotate_code(self, code=None):
        from videos.code_registry import code_digest_in_use

        if code:
            plain = normalize_access_code(code)
            if len(plain) != 10:
                raise ValueError("聊天室授权码必须为10位英文字母或数字")
        else:
            plain = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
        digest = digest_access_code(plain)
        if code_digest_in_use(digest, exclude_chat_room_id=self.pk):
            raise ValueError("该授权码已被其他内容使用，请更换一个")
        self.code_digest = digest
        self.code_hint = plain[-4:]
        self.save(update_fields=["code_digest", "code_hint", "updated_at"])
        return plain


class ChatParticipant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, related_name="participants", on_delete=models.CASCADE)
    token_digest = models.CharField("会话令牌摘要", max_length=64)
    ip_address = models.GenericIPAddressField("IP地址", null=True, blank=True)
    user_agent = models.TextField("User-Agent", blank=True)
    display_name = models.CharField("显示名称", max_length=30)
    avatar_seed = models.PositiveIntegerField("头像种子")
    joined_at = models.DateTimeField("进入时间", auto_now_add=True)
    last_seen_at = models.DateTimeField("最后在线时间", default=timezone.now)
    revoked_at = models.DateTimeField("撤销时间", null=True, blank=True)

    class Meta:
        ordering = ["-joined_at"]
        verbose_name = "聊天参与者"
        verbose_name_plural = "聊天参与者"
        constraints = [
            models.UniqueConstraint(fields=["room", "avatar_seed"], name="unique_chat_avatar_per_room"),
            models.UniqueConstraint(fields=["room", "display_name"], name="unique_chat_nickname_per_room"),
        ]
        indexes = [models.Index(fields=["room", "joined_at"])]

    def __str__(self):
        return f"{self.room.name} · {self.display_name}"

    @classmethod
    def create_for(cls, *, room, ip_address, user_agent):
        token = secrets.token_urlsafe(32)
        participant_id = uuid.uuid4()
        for attempt in range(30):
            position = room.participants.count() + attempt
            try:
                participant = cls.objects.create(
                    id=participant_id,
                    room=room,
                    token_digest=hashlib.sha256(token.encode()).hexdigest(),
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:2000],
                    display_name=nickname_for(room.nickname_group, position),
                    avatar_seed=secrets.randbelow(16_777_216),
                )
                return participant, token
            except IntegrityError:
                continue
        raise RuntimeError("无法为访客分配唯一头像")

    def token_matches(self, token):
        if not token:
            return False
        supplied = hashlib.sha256(token.encode()).hexdigest()
        return hmac.compare_digest(self.token_digest, supplied)

    def is_valid(self, ip_address=None):
        return (
            self.revoked_at is None
            and self.room.is_active
            and (not self.ip_address or self.ip_address == ip_address)
        )

    @property
    def cookie_name(self):
        return f"chat_{str(self.id).replace('-', '')}"

    @property
    def avatar_hue(self):
        return self.avatar_seed % 360

    @property
    def masked_ip(self):
        if not self.ip_address:
            return "未知IP"
        if ":" in self.ip_address:
            parts = self.ip_address.split(":")
            return ":".join(parts[:3]) + ":*"
        parts = self.ip_address.split(".")
        return ".".join(parts[:2]) + ".*.*"


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, related_name="messages", on_delete=models.CASCADE)
    participant = models.ForeignKey(
        ChatParticipant,
        related_name="messages",
        null=True,
        on_delete=models.SET_NULL,
    )
    body = models.TextField("消息正文")
    client_nonce = models.UUIDField("客户端消息编号")
    created_at = models.DateTimeField("发送时间", auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "聊天消息"
        verbose_name_plural = "聊天消息"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "client_nonce"],
                name="unique_chat_message_nonce",
            ),
        ]
        indexes = [models.Index(fields=["room", "-id"])]

    def __str__(self):
        return f"{self.room.name} · {self.participant or '已离开访客'} · {self.id}"
