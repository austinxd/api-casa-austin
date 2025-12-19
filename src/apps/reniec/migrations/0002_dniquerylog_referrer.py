# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reniec', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='dniquerylog',
            name='referrer',
            field=models.CharField(blank=True, help_text='URL de origen de la consulta', max_length=500, null=True),
        ),
    ]
