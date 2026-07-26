from django.contrib import admin

from .models import AccessCode, AdminAuditLog, PlaybackSession, SecurityEvent, Video, ViewEvent


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "processing_status", "sharing_enabled", "share_state", "last_seen_at")
    list_filter = ("processing_status", "sharing_enabled")
    search_fields = ("title", "source_path")
    readonly_fields = (
        "source_path", "source_size", "duration_seconds", "width", "height", "codec",
        "hls_relative_path", "processing_status", "processing_error", "discovered_at",
        "last_seen_at", "processed_at",
    )

    @admin.display(description="共享状态")
    def share_state(self, obj):
        return obj.sharing_status_label

    def has_add_permission(self, request):
        return False


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = ("video", "code_hint", "state", "starts_at", "expires_at", "created_at")
    list_filter = ("enabled", "starts_at", "expires_at")
    search_fields = ("video__title", "code_hint", "note")
    readonly_fields = ("code_digest", "code_hint", "created_by", "created_at")

    @admin.display(description="状态")
    def state(self, obj):
        return obj.state_label

    def has_add_permission(self, request):
        return False


@admin.register(PlaybackSession)
class PlaybackSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "access_code", "ip_address", "state", "authorized_at", "watched_seconds")
    list_filter = ("state", "authorized_at")
    readonly_fields = [field.name for field in PlaybackSession._meta.fields]


@admin.register(ViewEvent)
class ViewEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "session", "ip_address", "position_seconds", "occurred_at")
    list_filter = ("event_type", "occurred_at")
    readonly_fields = [field.name for field in ViewEvent._meta.fields]


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "ip_address", "code_fingerprint", "occurred_at")
    list_filter = ("event_type", "occurred_at")
    readonly_fields = [field.name for field in SecurityEvent._meta.fields]


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "target_type", "target_id", "created_at")
    readonly_fields = [field.name for field in AdminAuditLog._meta.fields]

admin.site.site_header = "私密视频系统管理"
admin.site.site_title = "私密视频"
admin.site.site_url = "/manage/"
