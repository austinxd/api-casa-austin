# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0057_add_location_to_homeassistant_device'),
    ]

    operations = [
        migrations.AddField(
            model_name='homeassistantdevice',
            name='requires_temperature_pool',
            field=models.BooleanField(
                default=False,
                help_text='Solo mostrar este dispositivo si la reserva activa tiene temperature_pool=True (ej: calefacción de piscina)'
            ),
        ),
    ]
