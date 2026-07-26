import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "private_video.settings")

app = Celery("private_video")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
