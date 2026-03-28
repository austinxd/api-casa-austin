import os
from io import BytesIO

from django.db import models
from django.core.files.base import ContentFile
from django.utils.text import slugify

from apps.core.models import BaseModel


def blog_image_upload_path(instance, filename):
    """Generate upload path for blog featured images."""
    name, ext = os.path.splitext(filename)
    safe_filename = f"{slugify(name)}{ext}"
    return f"blog_images/{instance.id}/{safe_filename}"


def blog_thumbnail_upload_path(instance, filename):
    """Generate upload path for blog thumbnails."""
    name, ext = os.path.splitext(filename)
    safe_filename = f"{slugify(name)}_thumb.webp"
    return f"blog_images/{instance.id}/{safe_filename}"


class BlogCategory(BaseModel):
    name = models.CharField(max_length=200, verbose_name="Nombre")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="Slug")
    description = models.TextField(blank=True, default="", verbose_name="Descripcion")
    order = models.PositiveIntegerField(default=0, verbose_name="Orden")

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Categoria del Blog"
        verbose_name_plural = "Categorias del Blog"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while BlogCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class BlogPost(BaseModel):
    STATUS_CHOICES = [
        ('draft', 'Borrador'),
        ('published', 'Publicado'),
    ]

    title = models.CharField(max_length=300, verbose_name="Titulo")
    slug = models.SlugField(max_length=300, unique=True, verbose_name="Slug")
    content = models.TextField(verbose_name="Contenido HTML")
    excerpt = models.TextField(blank=True, default="", verbose_name="Extracto")
    meta_description = models.CharField(
        max_length=160, blank=True, default="",
        verbose_name="Meta Description",
        help_text="Descripcion para SEO (max 160 caracteres)"
    )
    featured_image = models.ImageField(
        upload_to=blog_image_upload_path,
        blank=True, null=True,
        verbose_name="Imagen Destacada",
        help_text="Imagen principal del post"
    )
    thumbnail = models.ImageField(
        upload_to=blog_thumbnail_upload_path,
        blank=True, null=True,
        verbose_name="Thumbnail (400x300)",
        help_text="Generado automaticamente"
    )
    category = models.ForeignKey(
        BlogCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posts',
        verbose_name="Categoria"
    )
    author = models.CharField(max_length=200, blank=True, default="Casa Austin", verbose_name="Autor")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='draft',
        verbose_name="Estado"
    )
    published_date = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Fecha de Publicacion"
    )

    class Meta:
        ordering = ['-published_date']
        verbose_name = "Post del Blog"
        verbose_name_plural = "Posts del Blog"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            if not base_slug:
                base_slug = f"post-{str(self.pk)[:8]}" if self.pk else "post"
            slug = base_slug
            counter = 1
            while BlogPost.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Save first to have a file path
        super().save(*args, **kwargs)

        # Generate thumbnail if featured_image exists and no thumbnail yet
        if self.featured_image and not self.thumbnail:
            self.generate_thumbnail()
            super().save(update_fields=['thumbnail'])

    def generate_thumbnail(self):
        """Generate thumbnail from featured image (400x300) in WebP format."""
        try:
            from PIL import Image

            with Image.open(self.featured_image.path) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')

                target_width, target_height = 400, 300
                img_ratio = img.width / img.height
                target_ratio = target_width / target_height

                if img_ratio > target_ratio:
                    new_height = target_height
                    new_width = int(target_height * img_ratio)
                else:
                    new_width = target_width
                    new_height = int(target_width / img_ratio)

                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                thumbnail = Image.new('RGB', (target_width, target_height), (255, 255, 255))
                paste_x = (target_width - new_width) // 2
                paste_y = (target_height - new_height) // 2
                thumbnail.paste(img_resized, (paste_x, paste_y))

                output = BytesIO()
                thumbnail.save(output, format='WEBP', quality=85, optimize=True)
                output.seek(0)

                original_name = os.path.splitext(os.path.basename(self.featured_image.name))[0]
                thumbnail_name = f"{original_name}_thumb.webp"

                self.thumbnail.save(
                    thumbnail_name,
                    ContentFile(output.getvalue()),
                    save=False
                )
        except Exception as e:
            print(f"Error generando thumbnail del blog: {e}")

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()
