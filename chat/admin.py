from django.contrib import admin

from .models import ChatMessage, ChatParticipant, ChatRoom


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChatRoom)
class ChatRoomAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "full_authorization_code",
        "nickname_group_label",
        "is_active",
        "created_at",
        "last_message_at",
    )
    list_filter = ("is_active",)
    search_fields = ("name", "code_hint")
    readonly_fields = (
        "full_authorization_code",
        "code_digest",
        "code_hint",
        "created_at",
        "updated_at",
        "last_message_at",
    )

    @admin.display(description="完整授权码")
    def full_authorization_code(self, obj):
        return obj.revealed_code or f"历史码不可恢复（尾号 {obj.code_hint}）"


@admin.register(ChatParticipant)
class ChatParticipantAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("display_name", "room", "ip_address", "joined_at", "last_seen_at", "revoked_at")
    list_filter = ("room",)
    search_fields = ("display_name", "ip_address")
    readonly_fields = (
        "token_digest",
        "identity_digest",
        "device_fingerprint",
        "display_name",
        "avatar_seed",
        "joined_at",
        "last_seen_at",
        "revoked_at",
    )


@admin.register(ChatMessage)
class ChatMessageAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "room", "participant", "created_at", "body_preview")
    list_filter = ("room",)
    search_fields = ("body", "participant__display_name", "participant__ip_address")
    readonly_fields = (
        "room",
        "participant",
        "body",
        "image_relative_path",
        "image_content_type",
        "image_size",
        "image_width",
        "image_height",
        "client_nonce",
        "created_at",
    )

    @admin.display(description="消息")
    def body_preview(self, obj):
        return obj.body[:60] or ("[图片]" if obj.has_image else "")
