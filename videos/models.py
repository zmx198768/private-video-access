import hashlib
import hmac
import secrets
import string
import unicodedata
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def normalize_access_code(code):
    normalized = unicodedata.normalize("NFKC", code or "").upper()
    return "".join(character for character in normalized if character in string.ascii_uppercase + string.digits)


def digest_access_code(code):
    normalized = normalize_access_code(code)
    return hmac.new(
        settings.SECRET_KEY.encode(),
        normalized.encode(),
        hashlib.sha256,
    ).hexdigest()


class Video(models.Model):
    class ProcessingStatus(models.TextChoices):
        DISCOVERED = "discovered", "等待文件稳定"
        QUEUED = "queued", "等待转码"
        PROCESSING = "processing", "正在转码"
        READY = "ready", "可播放"
        FAILED = "failed", "处理失败"
        MISSING = "missing", "源文件缺失"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField("标题", max_length=255)
    source_key = models.CharField("源文件路径摘要", max_length=64, unique=True, db_index=True)
    source_path = models.TextField("源文件路径")
    source_size = models.BigIntegerField("文件大小", default=0)
    source_mtime_ns = models.BigIntegerField("修改时间戳", default=0)
    stable_scan_count = models.PositiveSmallIntegerField("稳定扫描次数", default=0)
    duration_seconds = models.DecimalField("时长（秒）", max_digits=12, decimal_places=3, null=True, blank=True)
    width = models.PositiveIntegerField("宽度", null=True, blank=True)
    height = models.PositiveIntegerField("高度", null=True, blank=True)
    codec = models.CharField("视频编码", max_length=64, blank=True)
    hls_relative_path = models.CharField("HLS相对路径", max_length=1024, blank=True)
    processing_status = models.CharField(
        "处理状态", max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.DISCOVERED
    )
    processing_error = models.TextField("处理错误", blank=True)
    sharing_enabled = models.BooleanField("允许共享", default=False)
    discovered_at = models.DateTimeField("发现时间", auto_now_add=True)
    last_seen_at = models.DateTimeField("最后扫描时间", default=timezone.now)
    processed_at = models.DateTimeField("处理完成时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-discovered_at"]
        verbose_name = "视频"
        verbose_name_plural = "视频"

    def __str__(self):
        return self.title

    @property
    def is_ready(self):
        return self.processing_status == self.ProcessingStatus.READY and bool(self.hls_relative_path)

    @property
    def active_code_count(self):
        now = timezone.now()
        return self.access_codes.filter(
            enabled=True,
            deleted_at__isnull=True,
            starts_at__lte=now,
            expires_at__gt=now,
        ).count()

    @property
    def is_currently_shared(self):
        return self.sharing_enabled and self.is_ready and self.active_code_count > 0

    @property
    def sharing_status_label(self):
        if self.processing_status == self.ProcessingStatus.MISSING:
            return "源文件缺失"
        if not self.is_ready:
            return self.get_processing_status_display()
        if not self.sharing_enabled:
            return "已停止共享"
        if self.active_code_count == 0:
            return "无有效授权码"
        return "正在共享"


class AccessCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video = models.ForeignKey(Video, related_name="access_codes", on_delete=models.PROTECT, verbose_name="视频")
    code_digest = models.CharField("授权码摘要", max_length=64, unique=True, db_index=True)
    code_hint = models.CharField("授权码尾号", max_length=4)
    starts_at = models.DateTimeField("生效时间", default=timezone.now)
    expires_at = models.DateTimeField("失效时间")
    enabled = models.BooleanField("启用", default=True)
    deleted_at = models.DateTimeField("删除时间", null=True, blank=True)
    note = models.CharField("备注", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="创建人"
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "授权码"
        verbose_name_plural = "授权码"
        indexes = [models.Index(fields=["video", "enabled", "expires_at"])]

    def __str__(self):
        return f"{self.video.title} · ****{self.code_hint}"

    @classmethod
    def issue(cls, *, video, expires_at, starts_at=None, note="", created_by=None):
        for _ in range(20):
            plain = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
            digest = digest_access_code(plain)
            if not cls.objects.filter(code_digest=digest).exists():
                obj = cls.objects.create(
                    video=video,
                    code_digest=digest,
                    code_hint=plain[-4:],
                    starts_at=starts_at or timezone.now(),
                    expires_at=expires_at,
                    note=note,
                    created_by=created_by,
                )
                return obj, plain
        raise RuntimeError("无法生成唯一授权码")

    @classmethod
    def issue_custom(cls, *, code, video, expires_at, starts_at=None, note="", created_by=None):
        plain = normalize_access_code(code)
        if len(plain) != 10:
            raise ValueError("授权码必须为10位英文字母或数字")
        digest = digest_access_code(plain)
        if cls.objects.filter(code_digest=digest).exists():
            raise ValueError("该授权码已存在，请更换一个")
        obj = cls.objects.create(
            video=video,
            code_digest=digest,
            code_hint=plain[-4:],
            starts_at=starts_at or timezone.now(),
            expires_at=expires_at,
            note=note,
            created_by=created_by,
        )
        return obj, plain

    def valid_at(self, moment=None):
        moment = moment or timezone.now()
        return self.deleted_at is None and self.enabled and self.starts_at <= moment < self.expires_at

    @property
    def state_label(self):
        now = timezone.now()
        if self.deleted_at:
            return "已删除"
        if not self.enabled:
            return "已停用"
        if now < self.starts_at:
            return "未生效"
        if now >= self.expires_at:
            return "已过期"
        return "有效"


class PlaybackSession(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "有效"
        REVOKED = "revoked", "已撤销"
        ENDED = "ended", "已结束"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    access_code = models.ForeignKey(AccessCode, related_name="sessions", on_delete=models.PROTECT)
    token_digest = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    authorized_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    watched_seconds = models.PositiveIntegerField(default=0)
    max_position_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-authorized_at"]
        verbose_name = "播放会话"
        verbose_name_plural = "播放会话"
        indexes = [models.Index(fields=["access_code", "authorized_at"])]

    @classmethod
    def create_for(cls, access_code, ip_address, user_agent):
        token = secrets.token_urlsafe(32)
        obj = cls.objects.create(
            access_code=access_code,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            ip_address=ip_address,
            user_agent=user_agent[:2000],
        )
        return obj, token

    def token_matches(self, token):
        if not token:
            return False
        supplied = hashlib.sha256(token.encode()).hexdigest()
        return hmac.compare_digest(self.token_digest, supplied)

    def is_valid(self):
        cutoff = timezone.now() - timezone.timedelta(hours=settings.PLAYBACK_SESSION_HOURS)
        return (
            self.state == self.State.ACTIVE
            and self.authorized_at >= cutoff
            and self.access_code.valid_at()
            and self.access_code.video.sharing_enabled
            and self.access_code.video.is_ready
        )


class ViewEvent(models.Model):
    class EventType(models.TextChoices):
        AUTHORIZED = "authorized", "授权成功"
        START = "start", "开始播放"
        HEARTBEAT = "heartbeat", "播放心跳"
        PAUSE = "pause", "暂停"
        SEEK = "seek", "拖动"
        ENDED = "ended", "播放结束"
        DENIED = "denied", "访问拒绝"

    session = models.ForeignKey(PlaybackSession, null=True, blank=True, related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    occurred_at = models.DateTimeField(auto_now_add=True)
    position_seconds = models.PositiveIntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "观看事件"
        verbose_name_plural = "观看事件"


class SecurityEvent(models.Model):
    event_type = models.CharField("类型", max_length=50)
    occurred_at = models.DateTimeField("时间", auto_now_add=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    code_fingerprint = models.CharField("授权码指纹", max_length=16, blank=True)
    user_agent = models.TextField("User-Agent", blank=True)
    detail = models.CharField("详情", max_length=255, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "安全事件"
        verbose_name_plural = "安全事件"


class AdminAuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64)
    detail = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "管理员审计"
        verbose_name_plural = "管理员审计"


class SystemSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    system_name = models.CharField("系统名称", max_length=80, default="私密视频授权播放系统")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="最后修改人",
    )
    updated_at = models.DateTimeField("最后修改时间", auto_now=True)

    class Meta:
        verbose_name = "系统设置"
        verbose_name_plural = "系统设置"

    def __str__(self):
        return self.system_name

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
