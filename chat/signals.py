from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .images import delete_chat_image
from .models import ChatMessage


@receiver(post_delete, sender=ChatMessage)
def delete_message_image_after_commit(sender, instance, **kwargs):
    if instance.image_relative_path:
        transaction.on_commit(
            lambda relative_path=instance.image_relative_path: delete_chat_image(
                relative_path
            )
        )
