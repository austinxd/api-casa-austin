
# Generated manually to fix foreign key issues with utf8mb4

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0005_property_off_temperature_pool_url_and_more'),
    ]

    operations = [
        # Deshabilitar verificaciones de foreign keys
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 0;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 1;"
        ),
        
        # Cambiar charset y collation de las tablas principales
        migrations.RunSQL(
            """
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            ALTER TABLE property_profitpropertyairbnb CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """,
            reverse_sql="""
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            ALTER TABLE property_profitpropertyairbnb CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            """
        ),
        
        # Agregar nuevos campos
        migrations.AddField(
            model_name='property',
            name='titulo',
            field=models.CharField(blank=True, max_length=200, null=True, verbose_name='Título'),
        ),
        migrations.AddField(
            model_name='property',
            name='descripcion',
            field=models.TextField(blank=True, null=True, verbose_name='Descripción'),
        ),
        migrations.AddField(
            model_name='property',
            name='dormitorios',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Número de dormitorios'),
        ),
        migrations.AddField(
            model_name='property',
            name='banos',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Número de baños'),
        ),
        migrations.AddField(
            model_name='property',
            name='detalle_dormitorios',
            field=models.JSONField(blank=True, default=dict, help_text='JSON con detalles de cada habitación', verbose_name='Detalle de dormitorios'),
        ),
        migrations.AddField(
            model_name='property',
            name='hora_ingreso',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora de ingreso'),
        ),
        migrations.AddField(
            model_name='property',
            name='hora_salida',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora de salida'),
        ),
        migrations.AddField(
            model_name='property',
            name='precio_extra_persona',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='Precio extra por persona'),
        ),
        migrations.AddField(
            model_name='property',
            name='precio_desde',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Precio base de referencia para mostrar en listados', max_digits=10, null=True, verbose_name='Precio desde'),
        ),
        migrations.AddField(
            model_name='property',
            name='caracteristicas',
            field=models.JSONField(blank=True, default=list, help_text='Lista de características de la propiedad', verbose_name='Características'),
        ),
        
        # Rehabilitar verificaciones de foreign keys
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 1;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 0;"
        ),
    ]
