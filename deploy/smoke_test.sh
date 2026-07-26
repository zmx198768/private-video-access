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
ADMIN_COOKIE_JAR=/tmp/private-video-admin-smoke-cookies.txt
DEFAULT_HOST="${DJANGO_ALLOWED_HOSTS%%,*}"
DEFAULT_SCHEME=http
if [[ "${COOKIE_SECURE:-0}" == "1" ]]; then
    DEFAULT_SCHEME=https
fi
BASE="${SMOKE_BASE_URL:-${DEFAULT_SCHEME}://${DEFAULT_HOST}}"

cleanup() {
    rm -f "$COOKIE_JAR" "$HEADERS" "$MANIFEST" "$BODY" "$ADMIN_COOKIE_JAR" "$SOURCE"
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

watch_status=$(curl -sS -o /dev/null -w '%{http_code}' -b "$COOKIE_JAR" "$BASE$location")
[[ "$watch_status" == 200 ]]
curl -fsS -b "$COOKIE_JAR" "$BASE/manifest/$session_id/index.m3u8" -o "$MANIFEST"
segment=$(grep -v '^#' "$MANIFEST" | sed -n '1p')
[[ -n "$segment" ]]
segment_status=$(curl -sS -o "$BODY" -w '%{http_code}' "$BASE$segment")
[[ "$segment_status" == 200 ]]
[[ -s "$BODY" ]]
direct_status=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/_protected_hls/$session_id/init.mp4")
[[ "$direct_status" == 404 ]]

echo "SMOKE_TEST_OK"
