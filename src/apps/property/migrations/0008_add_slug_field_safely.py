
from django.db import migrations, models
from django.utils.text import slugify


def generate_slugs(apps, schema_editor):
    Property = apps.get_model('property', 'Property')
    
    for prop in Property.objects.all():
        if prop.name:
            base_slug = slugify(prop.name)
        else:
            base_slug = f"propiedad-{prop.pk}"
        
        # Verificar si el slug ya existe
        counter = 1
        slug = base_slug
        while Property.objects.filter(slug=slug).exclude(pk=prop.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        # Actualizar el slug
        Property.objects.filter(pk=prop.pk).update(slug=slug)


def reverse_generate_slugs(apps, schema_editor):
    Property = apps.get_model('property', 'Property')
    Property.objects.all().update(slug='')


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0007_mark_slug_as_existing'),
    ]

    operations = [
        # Agregar el campo slug sin unique primero
        migrations.AddField(
            model_name='property',
            name='slug',
            field=models.SlugField(max_length=200, blank=True, verbose_name='Slug', help_text='URL amigable generada automáticamente'),
        ),
        # Generar slugs únicos para registros existentes
        migrations.RunPython(generate_slugs, reverse_generate_slugs),
        # Hacer el campo unique
        migrations.AlterField(
            model_name='property',
            name='slug',
            field=models.SlugField(max_length=200, unique=True, blank=True, verbose_name='Slug', help_text='URL amigable generada automáticamente'),
        ),
    ]
