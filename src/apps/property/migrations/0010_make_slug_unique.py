
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0009_generate_unique_slugs'),
    ]

    operations = [
        migrations.AlterField(
            model_name='property',
            name='slug',
            field=models.SlugField(max_length=200, unique=True, blank=True, verbose_name='Slug', help_text='URL amigable generada automáticamente'),
        ),
    ]
