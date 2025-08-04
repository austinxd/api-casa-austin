
from django.db import migrations
from django.utils.text import slugify


def generate_unique_slugs(apps, schema_editor):
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
        prop.slug = slug
        prop.save(update_fields=['slug'])


def reverse_generate_slugs(apps, schema_editor):
    Property = apps.get_model('property', 'Property')
    Property.objects.all().update(slug='')


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0008_add_slug_field'),
    ]

    operations = [
        migrations.RunPython(generate_unique_slugs, reverse_generate_slugs),
    ]
