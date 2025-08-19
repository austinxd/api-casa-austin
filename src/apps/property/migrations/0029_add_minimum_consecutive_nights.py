
# Generated migration for adding minimum_consecutive_nights to SpecialDatePricing

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0028_add_properties_to_dynamicdiscountconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='specialdatepricing',
            name='minimum_consecutive_nights',
            field=models.PositiveIntegerField(default=1, help_text='Número mínimo de noches consecutivas requeridas para esta fecha especial', validators=[django.core.validators.MinValueValidator(1)]),
        ),
    ]
