# Generated migration for adding status_sensor_entity_id to HomeAssistantDevice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0058_add_requires_temperature_pool'),
    ]

    operations = [
        migrations.AddField(
            model_name='homeassistantdevice',
            name='status_sensor_entity_id',
            field=models.CharField(
                blank=True,
                help_text='Entity ID de un sensor opcional para mostrar el estado real del dispositivo (ej: binary_sensor.garage_door_contact)',
                max_length=200,
                null=True,
            ),
        ),
    ]
