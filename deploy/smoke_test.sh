#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/private-video.env
set +a
cd /opt/private-video

SOURCE="${VIDEO_SOURCE_DIR%/}/codex-smoke-test.mp4"
COOKIE_JAR=/tmp/private-video-smoke-cookies.txt
HEADERS=/tmp/private-video-smoke-headers.txt
MANIFEST=/tmp/private-video-smoke.m3u8
BODY=/tmp/private-video-smoke-segment.bin
WATCH_HTML=/tmp/private-video-smoke-watch.html
ADMIN_COOKIE_JAR=/tmp/private-video-admin-smoke-cookies.txt
ADMIN_MANAGE_HTML=/tmp/private-video-admin-manage.html
CHAT_COOKIE_JAR=/tmp/private-video-chat-smoke-cookies.txt
CHAT_HEADERS=/tmp/private-video-chat-smoke-headers.txt
CHAT_IMAGE_UPLOAD=/tmp/private-video-chat-upload.png
CHAT_IMAGE_RESPONSE=/tmp/private-video-chat-image-response.json
CHAT_IMAGE_BODY=/tmp/private-video-chat-image.webp
CLIPBOARD_JS=/tmp/private-video-clipboard.js
CHAT_ROOM_ID=""
DEFAULT_HOST="${DJANGO_ALLOWED_HOSTS%%,*}"
DEFAULT_SCHEME=http
if [[ "${COOKIE_SECURE:-0}" == "1" ]]; then
    DEFAULT_SCHEME=https
fi
BASE="${SMOKE_BASE_URL:-${DEFAULT_SCHEME}://${DEFAULT_HOST}}"

web_ready=0
for _ in $(seq 1 20); do
    if curl -fsS "$BASE/health/" >/dev/null; then
        web_ready=1
        break
    fi
    sleep 1
done
[[ "$web_ready" == 1 ]]

cleanup() {
    rm -f "$COOKIE_JAR" "$HEADERS" "$MANIFEST" "$BODY" "$WATCH_HTML" \
        "$ADMIN_COOKIE_JAR" "$ADMIN_MANAGE_HTML" "$CHAT_COOKIE_JAR" "$CHAT_HEADERS" \
        "$CHAT_IMAGE_UPLOAD" "$CHAT_IMAGE_RESPONSE" "$CHAT_IMAGE_BODY" "$SOURCE"
    rm -f "$CLIPBOARD_JS"
    /opt/private-video/.venv/bin/python manage.py shell --no-imports -c "
from pathlib import Path
import shutil
from django.conf import settings
from videos.models import Video, AccessCode, PlaybackSession, ViewEvent
video = Video.objects.filter(source_path='$SOURCE').first()
if video:
    output = (settings.VIDEO_HLS_DIR / str(video.id)).resolve()
    root = settings.VIDEO_HLS_DIR.resolve()
    ViewEvent.objects.filter(session__access_code__video=video).delete()
    PlaybackSession.objects.filter(access_code__video=video).delete()
    AccessCode.objects.filter(video=video).delete()
    video.delete()
    if root in output.parents and output.exists():
        shutil.rmtree(output)
from chat.models import ChatRoom
if '$CHAT_ROOM_ID':
    ChatRoom.objects.filter(pk='$CHAT_ROOM_ID').delete()
"
}
trap cleanup EXIT

set -a
source /root/private-video-admin.txt
set +a
curl -fsS -c "$ADMIN_COOKIE_JAR" "$BASE/admin/login/?next=/manage/" >/dev/null
admin_csrf=$(awk '$6 == "csrftoken" {print $7}' "$ADMIN_COOKIE_JAR")
admin_login_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -b "$ADMIN_COOKIE_JAR" -c "$ADMIN_COOKIE_JAR" \
    -H "Referer: $BASE/admin/login/?next=/manage/" \
    --data-urlencode "csrfmiddlewaretoken=$admin_csrf" \
    --data-urlencode "username=$ADMIN_USERNAME" \
    --data-urlencode "password=$ADMIN_PASSWORD" \
    --data-urlencode "next=/manage/" \
    "$BASE/admin/login/?next=/manage/")
[[ "$admin_login_status" == 302 ]]
manage_status=$(curl -sS -o /dev/null -w '%{http_code}' -b "$ADMIN_COOKIE_JAR" "$BASE/manage/")
[[ "$manage_status" == 200 ]]
chat_manage_status=$(curl -sS -o /dev/null -w '%{http_code}' -b "$ADMIN_COOKIE_JAR" "$BASE/chat/manage/")
[[ "$chat_manage_status" == 200 ]]
chat_participants_status=$(curl -sS -o /dev/null -w '%{http_code}' -b "$ADMIN_COOKIE_JAR" "$BASE/chat/manage/participants/")
[[ "$chat_participants_status" == 200 ]]
entry_status=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/")
[[ "$entry_status" == 200 ]]
curl -fsS "$BASE/static/js/clipboard.js" -o "$CLIPBOARD_JS"
grep -Fq 'document.execCommand("copy")' "$CLIPBOARD_JS"
legacy_chat_entry_status=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/chat/")
[[ "$legacy_chat_entry_status" == 302 ]]
unset ADMIN_USERNAME ADMIN_PASSWORD

ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i testsrc=size=640x360:rate=24 \
    -f lavfi -i sine=frequency=1000:sample_rate=44100 \
    -t 3 -c:v libx264 -pix_fmt yuv420p -c:a aac "$SOURCE"
chown privatevideo:privatevideo "$SOURCE"

/opt/private-video/.venv/bin/python manage.py scan_videos >/dev/null
sleep 1
/opt/private-video/.venv/bin/python manage.py scan_videos >/dev/null

ready=0
for _ in $(seq 1 60); do
    status=$(/opt/private-video/.venv/bin/python manage.py shell --no-imports -c \
        "from videos.models import Video; print(Video.objects.get(source_path='$SOURCE').processing_status)")
    if [[ "$status" == "ready" ]]; then
        ready=1
        break
    fi
    if [[ "$status" == "failed" ]]; then
        /opt/private-video/.venv/bin/python manage.py shell --no-imports -c \
            "from videos.models import Video; print(Video.objects.get(source_path='$SOURCE').processing_error)"
        exit 1
    fi
    sleep 2
done
[[ "$ready" == 1 ]]

code=$(/opt/private-video/.venv/bin/python manage.py shell --no-imports -c "
from django.utils import timezone
from videos.models import Video, AccessCode
video = Video.objects.get(source_path='$SOURCE')
video.sharing_enabled = True
video.save(update_fields=['sharing_enabled'])
print(AccessCode.issue(video=video, expires_at=timezone.now()+timezone.timedelta(hours=1), note='smoke-test')[1])
")

curl -fsS -b "$ADMIN_COOKIE_JAR" "$BASE/manage/" -o "$ADMIN_MANAGE_HTML"
grep -Fq "$code" "$ADMIN_MANAGE_HTML"

chat_result=$(/opt/private-video/.venv/bin/python manage.py shell --no-imports -c "
from chat.models import ChatRoom
room, code = ChatRoom.create_with_code(name='smoke-test-chat-room')
print(f'{room.id}|{code}')
")
CHAT_ROOM_ID=${chat_result%%|*}
chat_code=${chat_result#*|}
curl -fsS -A "PrivateVideoSmoke/1.0" -c "$CHAT_COOKIE_JAR" "$BASE/" >/dev/null
chat_csrf=$(awk '$6 == "csrftoken" {print $7}' "$CHAT_COOKIE_JAR")
curl -fsS -A "PrivateVideoSmoke/1.0" -o /dev/null -D "$CHAT_HEADERS" \
    -b "$CHAT_COOKIE_JAR" -c "$CHAT_COOKIE_JAR" \
    -H "Referer: $BASE/" \
    --data-urlencode "csrfmiddlewaretoken=$chat_csrf" \
    --data-urlencode "code=$chat_code" \
    "$BASE/authorize/"
first_chat_location=$(awk 'tolower($1) == "location:" {gsub("\r", "", $2); print $2}' "$CHAT_HEADERS")
curl -fsS -A "PrivateVideoSmoke/1.0" -o /dev/null -D "$CHAT_HEADERS" \
    -b "$CHAT_COOKIE_JAR" -c "$CHAT_COOKIE_JAR" \
    -H "Referer: $BASE/" \
    --data-urlencode "csrfmiddlewaretoken=$chat_csrf" \
    --data-urlencode "code=$chat_code" \
    "$BASE/authorize/"
second_chat_location=$(awk 'tolower($1) == "location:" {gsub("\r", "", $2); print $2}' "$CHAT_HEADERS")
[[ "$first_chat_location" == "$second_chat_location" ]]
chat_participant_id=$(printf '%s' "$first_chat_location" | sed -E 's#^/chat/room/([^/]+)/$#\1#')
[[ -n "$chat_participant_id" ]]
participant_count=$(/opt/private-video/.venv/bin/python manage.py shell --no-imports -c "
from chat.models import ChatRoom
print(ChatRoom.objects.get(pk='$CHAT_ROOM_ID').participants.count())
")
[[ "$participant_count" == "1" ]]
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=' \
    | base64 -d > "$CHAT_IMAGE_UPLOAD"
curl -fsS -A "PrivateVideoSmoke/1.0" \
    -b "$CHAT_COOKIE_JAR" -c "$CHAT_COOKIE_JAR" \
    -H "Referer: $BASE/chat/room/$chat_participant_id/" \
    -H "X-CSRFToken: $chat_csrf" \
    -F "image=@$CHAT_IMAGE_UPLOAD;type=image/png" \
    "$BASE/chat/room/$chat_participant_id/upload-image/" \
    -o "$CHAT_IMAGE_RESPONSE"
chat_message_id=$(/opt/private-video/.venv/bin/python -c \
    'import json,sys; print(json.load(sys.stdin)["message"]["id"])' < "$CHAT_IMAGE_RESPONSE")
[[ -n "$chat_message_id" ]]
curl -fsS -A "PrivateVideoSmoke/1.0" -b "$CHAT_COOKIE_JAR" \
    "$BASE/chat/room/$chat_participant_id/image/$chat_message_id/" \
    -o "$CHAT_IMAGE_BODY"
[[ "$(head -c 4 "$CHAT_IMAGE_BODY")" == "RIFF" ]]
staff_image_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -b "$ADMIN_COOKIE_JAR" \
    "$BASE/chat/manage/messages/$chat_message_id/image/")
[[ "$staff_image_status" == 200 ]]
direct_chat_image_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    "$BASE/_protected_chat_images/$CHAT_ROOM_ID/test.webp")
[[ "$direct_chat_image_status" == 404 ]]
curl -fsS -b "$ADMIN_COOKIE_JAR" "$BASE/chat/manage/" -o "$ADMIN_MANAGE_HTML"
grep -Fq "$chat_code" "$ADMIN_MANAGE_HTML"

curl -fsS -c "$COOKIE_JAR" "$BASE/" >/dev/null
csrf=$(awk '$6 == "csrftoken" {print $7}' "$COOKIE_JAR")
curl -fsS -o /dev/null -D "$HEADERS" -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -H "Referer: $BASE/" \
    --data-urlencode "csrfmiddlewaretoken=$csrf" \
    --data-urlencode "code=$code" \
    "$BASE/authorize/"
location=$(awk 'tolower($1) == "location:" {gsub("\r", "", $2); print $2}' "$HEADERS")
session_id=$(printf '%s' "$location" | sed -E 's#^/watch/([^/]+)/$#\1#')
[[ -n "$session_id" ]]

watch_status=$(curl -sS -o "$WATCH_HTML" -w '%{http_code}' -b "$COOKIE_JAR" "$BASE$location")
[[ "$watch_status" == 200 ]]
! grep -q 'class="system-nav"' "$WATCH_HTML"
curl -fsS -b "$COOKIE_JAR" "$BASE/manifest/$session_id/index.m3u8" -o "$MANIFEST"
segment=$(grep -v '^#' "$MANIFEST" | sed -n '1p')
[[ -n "$segment" ]]
segment_status=$(curl -sS -o "$BODY" -w '%{http_code}' "$BASE$segment")
[[ "$segment_status" == 200 ]]
[[ -s "$BODY" ]]
direct_status=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/_protected_hls/$session_id/init.mp4")
[[ "$direct_status" == 404 ]]

reuse_status=$(/opt/private-video/.venv/bin/python manage.py shell --no-imports -c "
from django.utils import timezone
from videos.models import AccessCode, PlaybackSession, Video
video = Video.objects.get(source_path='$SOURCE')
old_code = AccessCode.objects.get(video=video, deleted_at__isnull=True)
old_session = PlaybackSession.objects.get(pk='$session_id')
old_code.enabled = False
old_code.deleted_at = timezone.now()
old_code.save(update_fields=['enabled', 'deleted_at'])
new_code, reused_plain = AccessCode.issue_custom(
    code='$code',
    video=video,
    expires_at=timezone.now() + timezone.timedelta(hours=1),
    note='smoke-test-reuse',
)
old_code.refresh_from_db()
old_session.refresh_from_db()
assert reused_plain == '$code'
assert new_code.pk != old_code.pk
assert old_code.active_digest is None
assert new_code.active_digest == new_code.code_digest
assert old_session.access_code_id == old_code.pk
assert AccessCode.objects.filter(video=video, code_digest=new_code.code_digest).count() == 2
print('REUSE_OK')
")
[[ "$reuse_status" == "REUSE_OK" ]]

echo "SMOKE_TEST_OK"
