# Separa capacity en 2: capacity_max (eventos) + capacity_sleep (dormir).
# Análisis del chatbot reveló que clientes interpretaban capacity_max
# (ej. CA3=100) como capacidad para dormir y llegaban con expectativas
# erradas. capacity_sleep es opcional: si está null, el bot usa capacity_max.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0060_securitycamera'),
    ]

    operations = [
        migrations.AlterField(
            model_name='property',
            name='capacity_max',
            field=models.IntegerField(
                blank=True, null=True,
                help_text='Capacidad TOTAL para eventos/fiestas (gente entrando, no necesariamente durmiendo).',
            ),
        ),
        migrations.AddField(
            model_name='property',
            name='capacity_sleep',
            field=models.IntegerField(
                blank=True, null=True,
                help_text=(
                    'Cantidad real de personas que pueden DORMIR (camas/colchones disponibles). '
                    'El chatbot usa este número cuando el cliente pregunta sobre alojamiento, y '
                    'capacity_max cuando pregunta sobre eventos.'
                ),
            ),
        ),
    ]
