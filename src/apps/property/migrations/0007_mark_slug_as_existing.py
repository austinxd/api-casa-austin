
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0006_fix_utf8mb4_encoding'),
    ]

    operations = [
        # Esta es una migración "fake" para marcar que el campo slug ya existe
        # Sin intentar crearlo nuevamente
    ]
