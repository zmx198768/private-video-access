#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_ORIGIN="${APP_ORIGIN:-http://${APP_HOST}}"
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
DB_ALLOWED_HOST="${DB_ALLOWED_HOST:-127.0.0.1}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DB="${REDIS_DB:-4}"
CHAT_REDIS_DB="${CHAT_REDIS_DB:-5}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

printf "MySQL root password: " >&2
read -rs MYSQL_ROOT_PASSWORD
printf "\nRedis password: " >&2
read -rs REDIS_PASSWORD
printf "\n" >&2

DB_APP_PASSWORD="$(openssl rand -hex 24)"
DJANGO_SECRET="$(openssl rand -hex 48)"
ACCESS_CODE_ENCRYPTION_KEY="$(openssl rand -hex 48)"
ADMIN_PASSWORD="$(openssl rand -hex 12)"
REDIS_PASSWORD_URLENCODED="$("$PYTHON_BIN" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REDIS_PASSWORD")"

export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_ROOT_USER" <<SQL
CREATE DATABASE IF NOT EXISTS private_video CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'private_video'@'${DB_ALLOWED_HOST}' IDENTIFIED BY '${DB_APP_PASSWORD}';
ALTER USER 'private_video'@'${DB_ALLOWED_HOST}' IDENTIFIED BY '${DB_APP_PASSWORD}';
GRANT ALL PRIVILEGES ON private_video.* TO 'private_video'@'${DB_ALLOWED_HOST}';
FLUSH PRIVILEGES;
SQL
unset MYSQL_PWD MYSQL_ROOT_PASSWORD

umask 077
{
    printf '%s\n' "DJANGO_SECRET_KEY=${DJANGO_SECRET}"
    printf '%s\n' "ACCESS_CODE_ENCRYPTION_KEY=${ACCESS_CODE_ENCRYPTION_KEY}"
    printf '%s\n' "DJANGO_DEBUG=0"
    printf '%s\n' "DJANGO_ALLOWED_HOSTS=${APP_HOST}"
    printf '%s\n' "CSRF_TRUSTED_ORIGINS=${APP_ORIGIN}"
    printf '%s\n' "DB_ENGINE=mysql"
    printf '%s\n' "DB_NAME=private_video"
    printf '%s\n' "DB_USER=private_video"
    printf '%s\n' "DB_PASSWORD=${DB_APP_PASSWORD}"
    printf '%s\n' "DB_HOST=${MYSQL_HOST}"
    printf '%s\n' "DB_PORT=${MYSQL_PORT}"
    printf '%s\n' "REDIS_URL=redis://:${REDIS_PASSWORD_URLENCODED}@${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
    printf '%s\n' "CHAT_REDIS_URL=redis://:${REDIS_PASSWORD_URLENCODED}@${REDIS_HOST}:${REDIS_PORT}/${CHAT_REDIS_DB}"
    printf '%s\n' "USE_REDIS_CACHE=1"
    printf '%s\n' "USE_REDIS_CHANNEL_LAYER=1"
    printf '%s\n' "CHAT_IDENTITY_DAYS=30"
    printf '%s\n' "CHAT_IMAGE_DIR=/var/lib/private-video/chat-images"
    printf '%s\n' "CHAT_IMAGE_MAX_BYTES=8388608"
    printf '%s\n' "CHAT_IMAGE_MAX_PIXELS=25000000"
    printf '%s\n' "CHAT_IMAGE_MAX_DIMENSION=4096"
    printf '%s\n' "VIDEO_SOURCE_DIR=/video"
    printf '%s\n' "VIDEO_HLS_DIR=/var/lib/private-video/hls"
    printf '%s\n' "TRUST_PROXY_HEADERS=1"
    printf '%s\n' "COOKIE_SECURE=0"
    printf '%s\n' "SECURE_SSL_REDIRECT=0"
    printf '%s\n' "TIME_ZONE=Asia/Shanghai"
} > /etc/private-video.env

{
    printf '%s\n' "ADMIN_USERNAME=admin"
    printf '%s\n' "ADMIN_PASSWORD=${ADMIN_PASSWORD}"
} > /root/private-video-admin.txt

chmod 600 /etc/private-video.env /root/private-video-admin.txt
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning ping >/dev/null
unset REDIS_PASSWORD REDIS_PASSWORD_URLENCODED DB_APP_PASSWORD DJANGO_SECRET ACCESS_CODE_ENCRYPTION_KEY ADMIN_PASSWORD
echo "CONFIGURED"
