
# Generated migration for post_action field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0039_remove_base_price_discount_trigger'),
    ]

    operations = [
        migrations.AddField(
            model_name='additionalservice',
            name='post_action',
            field=models.CharField(
                blank=True,
                help_text='Acción post-reserva que debe realizar el frontend (ej: temperature_pool)',
                max_length=50,
                null=True
            ),
        ),
    ]
