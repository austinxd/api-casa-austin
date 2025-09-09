
# Generated manually to add price_temperature_pool field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0019_alter_reservation_price_latecheckout'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='price_temperature_pool',
            field=models.DecimalField(blank=True, decimal_places=2, default=0, help_text='Precio cobrado por temperado de piscina', max_digits=10, null=True),
        ),
    ]
