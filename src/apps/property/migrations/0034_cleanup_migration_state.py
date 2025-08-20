
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('property', '0033_fix_migration_state'),
    ]

    operations = [
        # Esta migración está vacía intencionalmente
        # Solo sirve para marcar el estado como limpio después de 0033
    ]
