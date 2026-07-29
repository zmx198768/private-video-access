from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.entry, name="entry"),
    path("room/<uuid:participant_id>/", views.room, name="room"),
    path("room/<uuid:participant_id>/leave/", views.leave_room, name="leave"),
    path("room/<uuid:participant_id>/history/", views.history, name="history"),
    path("manage/", views.manage_rooms, name="manage"),
    path("manage/participants/", views.participant_records, name="participants"),
    path("manage/new/", views.create_room, name="create"),
    path("manage/<uuid:room_id>/messages/", views.message_records, name="message_records"),
    path("manage/<uuid:room_id>/toggle/", views.toggle_room, name="toggle"),
    path("manage/<uuid:room_id>/code/", views.rotate_code, name="rotate_code"),
]
