
# Generated for recurrent season pricing
from django.db import migrations, models
import django.core.validators
from decimal import Decimal


def convert_existing_seasons(apps, schema_editor):
    """Convierte las temporadas existentes a formato recurrente"""
    SeasonPricing = apps.get_model('property', 'SeasonPricing')
    
    for season in SeasonPricing.objects.all():
        # Usar start_date y end_date existentes para extraer mes y día
        if hasattr(season, 'start_date') and season.start_date:
            season.start_month = season.start_date.month
            season.start_day = season.start_date.day
        else:
            # Valores por defecto
            season.start_month = 1
            season.start_day = 1
            
        if hasattr(season, 'end_date') and season.end_date:
            season.end_month = season.end_date.month
            season.end_day = season.end_date.day
        else:
            # Valores por defecto
            season.end_month = 12
            season.end_day = 31
            
        season.save()


def reverse_conversion(apps, schema_editor):
    """Función de reversión (no realmente posible sin perder datos)"""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('property', '0018_alter_seasonpricing_options_and_more'),
    ]

    operations = [
        # Agregar nuevos campos
        migrations.AddField(
            model_name='seasonpricing',
            name='start_month',
            field=models.PositiveIntegerField(
                help_text='Mes de inicio (1-12)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)],
                default=1
            ),
        ),
        migrations.AddField(
            model_name='seasonpricing',
            name='start_day',
            field=models.PositiveIntegerField(
                help_text='Día de inicio (1-31)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)],
                default=1
            ),
        ),
        migrations.AddField(
            model_name='seasonpricing',
            name='end_month',
            field=models.PositiveIntegerField(
                help_text='Mes de fin (1-12)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)],
                default=12
            ),
        ),
        migrations.AddField(
            model_name='seasonpricing',
            name='end_day',
            field=models.PositiveIntegerField(
                help_text='Día de fin (1-31)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)],
                default=31
            ),
        ),
        
        # Convertir datos existentes
        migrations.RunPython(convert_existing_seasons, reverse_conversion),
        
        # Actualizar metadatos
        migrations.AlterModelOptions(
            name='seasonpricing',
            options={
                'ordering': ['start_month', 'start_day'],
                'verbose_name': '📅 Temporada Global Recurrente',
                'verbose_name_plural': '📅 Temporadas Globales Recurrentes'
            },
        ),
        
        # Remover campos antiguos
        migrations.RemoveField(
            model_name='seasonpricing',
            name='start_date',
        ),
        migrations.RemoveField(
            model_name='seasonpricing',
            name='end_date',
        ),
    ]
