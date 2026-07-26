from django.db import migrations
from django.utils import timezone


def soft_delete_disabled_codes(apps, schema_editor):
    AccessCode = apps.get_model("videos", "AccessCode")
    AccessCode.objects.filter(
        enabled=False,
        deleted_at__isnull=True,
    ).update(deleted_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0002_accesscode_deleted_at"),
    ]

    operations = [
        migrations.RunPython(soft_delete_disabled_codes, migrations.RunPython.noop),
    ]
