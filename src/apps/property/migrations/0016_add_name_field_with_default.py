
# Generated manually to fix name field issue
from django.db import migrations, models


def set_default_names(apps, schema_editor):
    """Establece nombres por defecto para las temporadas existentes"""
    SeasonPricing = apps.get_model('property', 'SeasonPricing')
    
    for season in SeasonPricing.objects.all():
        if season.season_type == 'high':
            season.name = f"Temporada Alta {season.start_date.year}"
        else:
            season.name = f"Temporada Baja {season.start_date.year}"
        season.save()


def reverse_default_names(apps, schema_editor):
    """Función de reversión (no necesaria)"""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('property', '0015_alter_seasonpricing_options_and_more'),
    ]

    operations = [
        # Primero agregar el campo como nullable
        migrations.AddField(
            model_name='seasonpricing',
            name='name',
            field=models.CharField(max_length=100, null=True, blank=True, help_text="Nombre de la temporada (ej: 'Verano 2024', 'Navidad y Año Nuevo')"),
        ),
        
        # Ejecutar la función para establecer valores por defecto
        migrations.RunPython(set_default_names, reverse_default_names),
        
        # Finalmente hacer el campo no nulo
        migrations.AlterField(
            model_name='seasonpricing',
            name='name',
            field=models.CharField(max_length=100, help_text="Nombre de la temporada (ej: 'Verano 2024', 'Navidad y Año Nuevo')"),
        ),
    ]
