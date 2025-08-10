
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0006_add_new_property_fields'),
    ]

    operations = [
        # Esta es una migración "fake" para marcar que el campo slug ya existe
        # Sin intentar crearlo nuevamente
    ]
