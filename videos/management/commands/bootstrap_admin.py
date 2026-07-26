import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "根据环境变量创建或更新管理员"

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        email = os.getenv("ADMIN_EMAIL", "")
        if not username or not password:
            raise CommandError("必须设置 ADMIN_USERNAME 和 ADMIN_PASSWORD")
        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(username=username)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"管理员 {username} 已就绪"))
