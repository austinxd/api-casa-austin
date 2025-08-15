# Generated manually to fix charset encoding - SQLite compatible version

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0005_property_off_temperature_pool_url_and_more'),
    ]

    operations = [
        # SQLite maneja automáticamente la codificación UTF-8
        # No necesitamos hacer nada específico para charset encoding en SQLite
        migrations.RunSQL(
            "SELECT 1;",  # Operación dummy que no hace nada pero es válida en SQLite
            reverse_sql="SELECT 1;"
        ),
    ]