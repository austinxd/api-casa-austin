# Generated manually to match production
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0022_musicsession_musicsessionparticipant'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='musicsession',
            options={'ordering': ['-created'], 'verbose_name': 'Sesión de Música', 'verbose_name_plural': 'Sesiones de Música'},
        ),
    ]
