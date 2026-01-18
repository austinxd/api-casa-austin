import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tv', '0002_add_welcome_message'),
    ]

    operations = [
        # Create TVAppVersion model
        migrations.CreateModel(
            name='TVAppVersion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('version_code', models.PositiveIntegerField(help_text='Numeric version code (e.g., 1, 2, 3). Must be higher than previous for updates.')),
                ('version_name', models.CharField(help_text="Human-readable version (e.g., '1.0.0', '1.1.0')", max_length=20)),
                ('apk_file', models.FileField(help_text='APK file for this version', upload_to='tv-app/apks/')),
                ('release_notes', models.TextField(blank=True, help_text="What's new in this version (shown to admins)")),
                ('is_current', models.BooleanField(default=False, help_text='Mark as current version to push updates to all TVs')),
                ('force_update', models.BooleanField(default=False, help_text='Force update even if user is watching content')),
                ('min_version_code', models.PositiveIntegerField(default=1, help_text='Minimum version code required to update (for compatibility)')),
            ],
            options={
                'verbose_name': 'TV App Version',
                'verbose_name_plural': 'TV App Versions',
                'ordering': ['-version_code'],
            },
        ),
    ]
