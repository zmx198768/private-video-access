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
    list_display = ("name", "nickname_group_label", "is_active", "code_hint", "created_at", "last_message_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code_hint")
    readonly_fields = ("code_digest", "code_hint", "created_at", "updated_at", "last_message_at")


@admin.register(ChatParticipant)
class ChatParticipantAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("display_name", "room", "ip_address", "joined_at", "last_seen_at", "revoked_at")
    list_filter = ("room",)
    search_fields = ("display_name", "ip_address")
    readonly_fields = (
        "token_digest",
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
    readonly_fields = ("room", "participant", "body", "client_nonce", "created_at")

    @admin.display(description="消息")
    def body_preview(self, obj):
        return obj.body[:60]
