from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("videos", "0004_systemsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="ip_blacklist",
            field=models.TextField(blank=True, default="", verbose_name="IP黑名单"),
        ),
    ]
