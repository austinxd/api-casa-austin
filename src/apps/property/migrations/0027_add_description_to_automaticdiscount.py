
# Generated migration for adding description field to AutomaticDiscount

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0026_propertyphoto_thumbnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='automaticdiscount',
            name='description',
            field=models.TextField(blank=True, help_text='Descripción detallada del descuento automático y sus condiciones', null=True),
        ),
    ]
