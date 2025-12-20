import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('property', '0001_initial'),
        ('reservation', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TVDevice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('deleted', models.BooleanField(default=False)),
                ('room_id', models.CharField(help_text='Unique identifier for this TV/room', max_length=50, unique=True)),
                ('room_name', models.CharField(blank=True, help_text="Friendly name for the room (e.g., 'Living Room', 'Master Bedroom')", max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('last_heartbeat', models.DateTimeField(blank=True, null=True)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tv_devices', to='property.property')),
            ],
            options={
                'verbose_name': 'TV Device',
                'verbose_name_plural': 'TV Devices',
                'ordering': ['property', 'room_name'],
            },
        ),
        migrations.CreateModel(
            name='TVSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('deleted', models.BooleanField(default=False)),
                ('event_type', models.CharField(choices=[('check_in', 'Check In'), ('check_out', 'Check Out'), ('heartbeat', 'Heartbeat'), ('app_launch', 'App Launch'), ('idle', 'Idle')], max_length=20)),
                ('event_data', models.JSONField(blank=True, help_text='Additional event data (e.g., app name for app_launch)', null=True)),
                ('reservation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tv_sessions', to='reservation.reservation')),
                ('tv_device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='tv.tvdevice')),
            ],
            options={
                'verbose_name': 'TV Session',
                'verbose_name_plural': 'TV Sessions',
                'ordering': ['-created'],
            },
        ),
    ]
