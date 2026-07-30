from django.apps import AppConfig


class ChatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chat"
    verbose_name = "私密聊天"

    def ready(self):
        from . import signals  # noqa: F401
