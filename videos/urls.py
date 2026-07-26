from django.urls import path

from . import views

app_name = "videos"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("csrf-token/", views.fresh_csrf_token, name="csrf_token"),
    path("", views.access_page, name="access"),
    path("authorize/", views.authorize, name="authorize"),
    path("watch/<uuid:session_id>/", views.watch, name="watch"),
    path("watch/<uuid:session_id>/event/", views.playback_event, name="playback_event"),
    path("manifest/<uuid:session_id>/index.m3u8", views.manifest, name="manifest"),
    path("stream/<uuid:session_id>/<path:filename>", views.stream_asset, name="stream_asset"),
    path("manage/", views.manage_dashboard, name="manage"),
    path("manage/settings/", views.manage_settings, name="settings"),
    path("manage/records/", views.view_records, name="records"),
    path("manage/upload/", views.upload_video, name="upload_video"),
    path("manage/video/<uuid:video_id>/rename/", views.rename_video, name="rename_video"),
    path("manage/video/<uuid:video_id>/codes/new/", views.create_codes, name="create_codes"),
    path("manage/video/<uuid:video_id>/toggle/", views.toggle_video_share, name="toggle_video"),
    path("manage/code/<uuid:code_id>/delete/", views.delete_code, name="delete_code"),
]
