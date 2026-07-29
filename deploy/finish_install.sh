#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

set -a
source /etc/private-video.env
set +a

if [[ "${1:-}" == "--reset-empty-database" ]]; then
    export MYSQL_PWD="$DB_PASSWORD"
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" <<SQL
DROP DATABASE IF EXISTS \`${DB_NAME}\`;
CREATE DATABASE \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SQL
    unset MYSQL_PWD
fi

cd /opt/private-video
chmod 700 deploy/configure_secrets.sh deploy/finish_install.sh deploy/smoke_test.sh
/opt/private-video/.venv/bin/python manage.py migrate --noinput
/opt/private-video/.venv/bin/python manage.py collectstatic --noinput

set -a
source /root/private-video-admin.txt
set +a
/opt/private-video/.venv/bin/python manage.py bootstrap_admin
unset ADMIN_USERNAME ADMIN_PASSWORD

install -m 0644 deploy/private-video-web.service /etc/systemd/system/private-video-web.service
install -m 0644 deploy/private-video-chat.service /etc/systemd/system/private-video-chat.service
install -m 0644 deploy/private-video-worker.service /etc/systemd/system/private-video-worker.service
install -m 0644 deploy/private-video-beat.service /etc/systemd/system/private-video-beat.service
install -m 0644 deploy/nginx-private-video.conf /etc/nginx/conf.d/private-video.conf
usermod -a -G privatevideo nginx
chown -R privatevideo:privatevideo /opt/private-video /var/lib/private-video /video

nginx -t
systemctl daemon-reload
systemctl enable --now private-video-web private-video-chat private-video-worker private-video-beat nginx
echo "INSTALLED"
