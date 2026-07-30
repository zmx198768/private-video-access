from django.apps import apps


def code_digest_in_use(
    digest,
    *,
    exclude_video_code_id=None,
    exclude_chat_room_id=None,
):
    access_code_model = apps.get_model("videos", "AccessCode")
    chat_room_model = apps.get_model("chat", "ChatRoom")

    video_codes = access_code_model.objects.filter(
        code_digest=digest,
        deleted_at__isnull=True,
    )
    if exclude_video_code_id:
        video_codes = video_codes.exclude(pk=exclude_video_code_id)

    chat_rooms = chat_room_model.objects.filter(code_digest=digest)
    if exclude_chat_room_id:
        chat_rooms = chat_rooms.exclude(pk=exclude_chat_room_id)

    return video_codes.exists() or chat_rooms.exists()
