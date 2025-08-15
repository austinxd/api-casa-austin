
# Generated for recurrent special date pricing
from django.db import migrations, models
import django.core.validators
from decimal import Decimal


def convert_existing_special_dates(apps, schema_editor):
    """Convierte las fechas especiales existentes a formato recurrente"""
    SpecialDatePricing = apps.get_model('property', 'SpecialDatePricing')
    
    for special_date in SpecialDatePricing.objects.all():
        # Usar date existente para extraer mes y día
        if hasattr(special_date, 'date') and special_date.date:
            special_date.month = special_date.date.month
            special_date.day = special_date.date.day
        else:
            # Valores por defecto para casos sin fecha
            special_date.month = 12
            special_date.day = 25  # Navidad como defecto
            
        special_date.save()


def reverse_conversion(apps, schema_editor):
    """Función de reversión (no realmente posible sin perder datos)"""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('property', '0020_alter_seasonpricing_end_day_and_more'),
    ]

    operations = [
        # Agregar nuevos campos
        migrations.AddField(
            model_name='specialdatepricing',
            name='month',
            field=models.PositiveIntegerField(
                help_text='Mes de la fecha especial (1-12)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)],
                default=12
            ),
        ),
        migrations.AddField(
            model_name='specialdatepricing',
            name='day',
            field=models.PositiveIntegerField(
                help_text='Día de la fecha especial (1-31)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)],
                default=25
            ),
        ),
        
        # Convertir datos existentes
        migrations.RunPython(convert_existing_special_dates, reverse_conversion),
        
        # Actualizar metadatos
        migrations.AlterModelOptions(
            name='specialdatepricing',
            options={
                'ordering': ['property', 'month', 'day'],
                'verbose_name': '🎉 Precio Fecha Especial Recurrente',
                'verbose_name_plural': '🎉 Precios Fechas Especiales Recurrentes'
            },
        ),
        
        # Actualizar unique_together
        migrations.AlterUniqueTogether(
            name='specialdatepricing',
            unique_together={('property', 'month', 'day')},
        ),
        
        # Remover campo antiguo
        migrations.RemoveField(
            model_name='specialdatepricing',
            name='date',
        ),
    ]
