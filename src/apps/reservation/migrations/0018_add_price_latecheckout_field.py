
# Generated manually to fix missing price_latecheckout column

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0017_reservation_price_latecheckout'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='price_latecheckout',
            field=models.DecimalField(blank=True, decimal_places=2, default=0, help_text='Precio adicional por late checkout', max_digits=10, null=True),
        ),
    ]
