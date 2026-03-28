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


class SearchConsoleData(BaseModel):
    """Cache de datos de Google Search Console para análisis de keywords."""
    query = models.CharField(max_length=500, verbose_name="Keyword")
    clicks = models.IntegerField(default=0, verbose_name="Clicks")
    impressions = models.IntegerField(default=0, verbose_name="Impresiones")
    ctr = models.FloatField(default=0, verbose_name="CTR %")
    position = models.FloatField(default=0, verbose_name="Posición promedio")
    page_url = models.URLField(max_length=500, blank=True, default="", verbose_name="URL de página")
    date_range_start = models.DateField(verbose_name="Inicio del rango")
    date_range_end = models.DateField(verbose_name="Fin del rango")
    synced_at = models.DateTimeField(auto_now=True, verbose_name="Última sincronización")

    class Meta:
        ordering = ['-impressions']
        unique_together = ['query', 'date_range_start', 'date_range_end']
        verbose_name = "Dato de Search Console"
        verbose_name_plural = "Datos de Search Console"

    def __str__(self):
        return f"{self.query} ({self.impressions} imp, pos {self.position:.1f})"


class BlogTopicPlan(BaseModel):
    """Registro de temas generados para rotación y tracking."""
    TOPIC_TYPES = [
        ('search_console', 'Basado en Search Console'),
        ('property', 'Propiedad Destacada'),
        ('lima_travel', 'Turismo Lima'),
        ('beaches', 'Playas'),
        ('seasonal', 'Estacional'),
        ('tips', 'Tips de Viaje'),
        ('events', 'Eventos'),
        ('gastronomy', 'Gastronomía'),
        ('family', 'Familia'),
    ]

    topic_type = models.CharField(max_length=20, choices=TOPIC_TYPES, verbose_name="Tipo de tema")
    topic_key = models.CharField(max_length=100, verbose_name="Clave del tema")
    topic_description = models.TextField(verbose_name="Descripción del tema")
    target_keyword = models.CharField(max_length=200, blank=True, default="", verbose_name="Keyword objetivo")
    blog_post = models.ForeignKey(
        BlogPost,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='topic_plans',
        verbose_name="Post generado"
    )
    generated_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de generación")

    class Meta:
        ordering = ['-generated_at']
        verbose_name = "Plan de Tema del Blog"
        verbose_name_plural = "Planes de Temas del Blog"

    def __str__(self):
        return f"[{self.get_topic_type_display()}] {self.topic_key}"
