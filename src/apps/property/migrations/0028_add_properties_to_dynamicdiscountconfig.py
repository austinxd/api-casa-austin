
# Generated migration for adding properties field to DynamicDiscountConfig

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0027_add_description_to_automaticdiscount'),
    ]

    operations = [
        migrations.AddField(
            model_name='dynamicdiscountconfig',
            name='properties',
            field=models.ManyToManyField(blank=True, help_text='Propiedades donde serán válidos los códigos generados (vacío = todas)', to='property.property'),
        ),
    ]
