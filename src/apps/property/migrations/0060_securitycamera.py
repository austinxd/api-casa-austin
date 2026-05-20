# Manual migration: agrega cámaras de seguridad (links de stream, no son
# dispositivos de Home Assistant).

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0059_add_status_sensor_to_homeassistant_device'),
    ]

    operations = [
        migrations.CreateModel(
            name='SecurityCamera',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('name', models.CharField(help_text="Nombre amigable (ej: 'Frente', 'Piscina', 'Garaje')", max_length=100)),
                ('stream_url', models.URLField(help_text='URL completa del stream (ej: https://pushvideo.casaaustin.pe/stream.html?src=cam8)', max_length=500)),
                ('location', models.CharField(blank=True, default='Cámaras', help_text="Agrupación visual (default: 'Cámaras')", max_length=100)),
                ('display_order', models.IntegerField(default=0, help_text='Orden de visualización')),
                ('is_active', models.BooleanField(default=True, help_text='¿La cámara está disponible?')),
                ('property', models.ForeignKey(help_text='Propiedad a la que pertenece la cámara', on_delete=django.db.models.deletion.CASCADE, related_name='security_cameras', to='property.property')),
            ],
            options={
                'verbose_name': 'Cámara de seguridad',
                'verbose_name_plural': 'Cámaras de seguridad',
                'ordering': ['property', 'display_order', 'name'],
            },
        ),
    ]
