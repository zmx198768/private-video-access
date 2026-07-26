from django.core.management.base import BaseCommand

from videos.tasks import scan_video_directory


class Command(BaseCommand):
    help = "立即扫描视频目录"

    def handle(self, *args, **options):
        result = scan_video_directory()
        self.stdout.write(self.style.SUCCESS(str(result)))
