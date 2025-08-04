
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0007_mark_slug_as_existing'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='slug',
            field=models.SlugField(max_length=200, blank=True, verbose_name='Slug', help_text='URL amigable generada automáticamente'),
        ),
    ]
