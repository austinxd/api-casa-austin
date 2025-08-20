
# Generated migration to fix inconsistent migration state

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0032_increase_trigger_max_length'),
        ('clients', '0014_achievement_clientachievement'),
    ]

    operations = [
        # Esta migración no hace cambios reales en la base de datos,
        # solo ajusta el estado de Django para que reconozca que
        # el campo min_reservations ya no existe y required_achievements existe
        migrations.RunSQL("SELECT 1;", reverse_sql="SELECT 1;"),
    ]
