
from django.db import models

from apps.core.models import BaseModel
from django.core.validators import MinValueValidator, MaxValueValidator


class Property(BaseModel):
    name = models.CharField(max_length=150, null=False, blank=False)
    location = models.CharField(max_length=250, null=True, blank=True)
    airbnb_url = models.URLField(null=True, blank=True)
    capacity_max = models.IntegerField(null=True, blank=True)
    background_color = models.CharField(max_length=255, null=False, blank=False, default="#fff")
    on_temperature_pool_url = models.URLField(null=True, blank=True)
    off_temperature_pool_url = models.URLField(null=True, blank=True)

    # Nuevos campos
    titulo = models.CharField(max_length=200, null=True, blank=True, verbose_name="Título")
    descripcion = models.TextField(null=True, blank=True, verbose_name="Descripción")
    dormitorios = models.PositiveIntegerField(null=True, blank=True, verbose_name="Número de dormitorios")
    banos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Número de baños")
    detalle_dormitorios = models.JSONField(default=dict, blank=True, verbose_name="Detalle de dormitorios", help_text="JSON con detalles de cada habitación")
    hora_ingreso = models.TimeField(null=True, blank=True, verbose_name="Hora de ingreso")
    hora_salida = models.TimeField(null=True, blank=True, verbose_name="Hora de salida")
    precio_extra_persona = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Precio extra por persona")
    precio_desde = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Precio desde", help_text="Precio base de referencia para mostrar en listados")
    caracteristicas = models.JSONField(default=list, blank=True, verbose_name="Características", help_text="Lista de características de la propiedad")
    slug = models.SlugField(max_length=200, unique=True, blank=True, verbose_name="Slug", help_text="URL amigable generada automáticamente")

    def __str__(self):
        return self.name

    def generate_slug(self):
        """Generar un slug basado en el nombre para URLs amigables"""
        import re
        from django.utils.text import slugify

        base_slug = slugify(self.name)
        if not base_slug:
            base_slug = slugify(f"propiedad-{self.pk}")

        # Verificar si el slug ya existe
        counter = 1
        slug = base_slug
        while Property.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_slug()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()


class PropertyPhoto(BaseModel):
    property = models.ForeignKey(Property, related_name='photos', on_delete=models.CASCADE)
    image_url = models.URLField(verbose_name="URL de la imagen")
    alt_text = models.CharField(max_length=200, blank=True, verbose_name="Texto alternativo")
    order = models.PositiveIntegerField(default=0, verbose_name="Orden", help_text="Orden de visualización (0 = primera)")
    is_main = models.BooleanField(default=False, verbose_name="Imagen principal")

    class Meta:
        ordering = ['order']
        verbose_name = "Foto de Propiedad"
        verbose_name_plural = "Fotos de Propiedades"

    def __str__(self):
        return f"Foto de {self.property.name} - {self.order}"

    def save(self, *args, **kwargs):
        # Si esta foto se marca como principal, desmarcar las demás de la misma propiedad
        if self.is_main:
            PropertyPhoto.objects.filter(property=self.property, is_main=True).exclude(pk=self.pk).update(is_main=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()


class ProfitPropertyAirBnb(BaseModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=False, blank=False)
    month = models.PositiveIntegerField(
        null=False, 
        blank=False, 
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ]
    )
    year = models.PositiveIntegerField(null=False, blank=False, default=1)
    profit_sol = models.DecimalField(max_digits=20, decimal_places=2, verbose_name='Ganancia (Soles)')

    class Meta:
        unique_together = ('property', 'month', 'year')

    def __str__(self):
        return f"Ganancia AirBnB {self.property.name} - Mes: {self.month} Año: {self.year}"
