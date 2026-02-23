
from django.db import models
from PIL import Image
import os
from django.core.files.base import ContentFile
from io import BytesIO

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
    precio_extra_persona = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        verbose_name="Precio extra por persona adicional (después de la 1ra persona)",
        help_text="Precio que se cobra por cada persona adicional después de la primera, por noche"
    )
    precio_desde = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Precio desde", help_text="Precio base de referencia para mostrar en listados")
    caracteristicas = models.JSONField(default=list, blank=True, verbose_name="Características", help_text="Lista de características de la propiedad")
    slug = models.SlugField(max_length=200, unique=True, blank=True, verbose_name="Slug", help_text="URL amigable generada automáticamente")
    player_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="ID de Casa",
        help_text="Escribe el ID de la casa (ej: ca1, ca2, ca3, ca4)"
    )
    guest_instructions = models.TextField(
        null=True,
        blank=True,
        verbose_name="Instrucciones para huéspedes",
        help_text="Info para el chatbot: WiFi, dirección, estacionamiento, qué traer, instrucciones de llegada, etc."
    )

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


def validate_image_size(value):
    """Validate image file size (max 20MB)"""
    from django.core.exceptions import ValidationError
    
    if value.size > 20 * 1024 * 1024:  # 20MB
        raise ValidationError('El archivo es demasiado grande. Tamaño máximo permitido: 20MB')


def property_photo_upload_path(instance, filename):
    """Generate upload path for property photos"""
    import os
    from django.utils.text import slugify
    
    # Get file extension
    name, ext = os.path.splitext(filename)
    
    # Generate safe filename
    safe_filename = f"{slugify(instance.property.name)}_{instance.order}_{slugify(name)}{ext}"
    
    return f"property_photos/{instance.property.id}/{safe_filename}"


class PropertyPhoto(BaseModel):
    property = models.ForeignKey(Property, related_name='photos', on_delete=models.CASCADE)
    image_url = models.URLField(blank=True, null=True, verbose_name="URL de la imagen")
    image_file = models.ImageField(
        upload_to=property_photo_upload_path, 
        blank=True, 
        null=True,
        verbose_name="Archivo de imagen",
        validators=[validate_image_size],
        help_text="Tamaño máximo: 20MB. Formatos permitidos: JPG, PNG, GIF"
    )
    thumbnail = models.ImageField(
        upload_to=property_photo_upload_path,
        blank=True,
        null=True,
        verbose_name="Thumbnail (400x300)",
        help_text="Imagen optimizada para cards, generada automáticamente"
    )
    alt_text = models.CharField(max_length=200, blank=True, verbose_name="Texto alternativo")
    order = models.PositiveIntegerField(default=0, verbose_name="Orden", help_text="Orden de visualización (0 = primera)")
    is_main = models.BooleanField(default=False, verbose_name="Imagen principal")

    class Meta:
        ordering = ['order']
        verbose_name = "Foto de Propiedad"
        verbose_name_plural = "Fotos de Propiedades"

    def __str__(self):
        return f"Foto de {self.property.name} - {self.order}"

    def get_image_url(self):
        """Get the image URL - prioritize uploaded file over external URL"""
        if self.image_file:
            return self.image_file.url
        return self.image_url or ""

    def get_thumbnail_url(self):
        """Get the thumbnail URL"""
        if self.thumbnail:
            return self.thumbnail.url
        return None

    def generate_thumbnail(self):
        """Generate thumbnail from main image (400x300) in WebP format"""
        if not self.image_file:
            return

        try:
            # Abrir la imagen original
            with Image.open(self.image_file.path) as img:
                # Convertir a RGB si es necesario (para WebP)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')

                # Calcular dimensiones manteniendo aspect ratio
                target_width, target_height = 400, 300
                img_ratio = img.width / img.height
                target_ratio = target_width / target_height

                if img_ratio > target_ratio:
                    # Imagen más ancha, ajustar por altura
                    new_height = target_height
                    new_width = int(target_height * img_ratio)
                else:
                    # Imagen más alta, ajustar por ancho
                    new_width = target_width
                    new_height = int(target_width / img_ratio)

                # Redimensionar
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Crear thumbnail centrado de 400x300
                thumbnail = Image.new('RGB', (target_width, target_height), (255, 255, 255))
                paste_x = (target_width - new_width) // 2
                paste_y = (target_height - new_height) // 2
                thumbnail.paste(img_resized, (paste_x, paste_y))

                # Guardar como WebP
                output = BytesIO()
                thumbnail.save(output, format='WEBP', quality=85, optimize=True)
                output.seek(0)

                # Generar nombre del archivo
                original_name = os.path.splitext(os.path.basename(self.image_file.name))[0]
                thumbnail_name = f"{original_name}_thumb.webp"

                # Guardar el thumbnail
                self.thumbnail.save(
                    thumbnail_name,
                    ContentFile(output.getvalue()),
                    save=False
                )

        except Exception as e:
            print(f"Error generando thumbnail: {e}")

    def clean(self):
        """Validate that either image_file or image_url is provided"""
        from django.core.exceptions import ValidationError
        
        if not self.image_file and not self.image_url:
            raise ValidationError("Debe proporcionar una imagen (archivo o URL)")
        
        super().clean()

    def save(self, *args, **kwargs):
        # Si esta foto se marca como principal, desmarcar las demás de la misma propiedad
        if self.is_main:
            PropertyPhoto.objects.filter(property=self.property, is_main=True).exclude(pk=self.pk).update(is_main=False)
        
        # Guardar primero
        super().save(*args, **kwargs)
        
        # Generar thumbnail si es foto principal y no tiene thumbnail
        if self.is_main and self.image_file and not self.thumbnail:
            self.generate_thumbnail()
            super().save(update_fields=['thumbnail'])

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


class ReferralDiscountByLevel(BaseModel):
    """Descuentos para primera reserva de clientes referidos según nivel del referidor"""
    
    achievement = models.ForeignKey(
        'clients.Achievement',
        on_delete=models.CASCADE,
        help_text="Nivel/Logro del cliente que refiere"
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Porcentaje de descuento para primera reserva del referido (0-100)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Activar/desactivar este descuento"
    )
    
    class Meta:
        ordering = ['achievement__order', 'achievement__required_reservations']
        verbose_name = "Descuento de Referido por Nivel"
        verbose_name_plural = "Descuentos de Referidos por Nivel"
        unique_together = ('achievement',)
    
    def __str__(self):
        return f"{self.achievement.name}: {self.discount_percentage}% en primera reserva"


class HomeAssistantDevice(BaseModel):
    """Dispositivos de Home Assistant controlables por propiedad"""
    
    class DeviceType(models.TextChoices):
        LIGHT = "light", "Luz"
        CLIMATE = "climate", "Clima/Calefacción"
        SWITCH = "switch", "Interruptor"
        COVER = "cover", "Cortina/Persiana"
        SCENE = "scene", "Escena"
        FAN = "fan", "Ventilador"
        MEDIA_PLAYER = "media_player", "Reproductor Multimedia"
        LOCK = "lock", "Cerradura"
        CAMERA = "camera", "Cámara"
        SENSOR = "sensor", "Sensor"
        OTHER = "other", "Otro"
    
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='homeassistant_devices',
        help_text="Propiedad a la que pertenece este dispositivo"
    )
    entity_id = models.CharField(
        max_length=200,
        help_text="Entity ID del dispositivo en Home Assistant (ej: light.sala_principal)"
    )
    friendly_name = models.CharField(
        max_length=200,
        help_text="Nombre amigable para mostrar al usuario (ej: Luz Principal)"
    )
    location = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Ubicación del dispositivo para agrupar en el frontend (ej: 2do Piso, Área Piscina, Sala Principal)"
    )
    device_type = models.CharField(
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.LIGHT,
        help_text="Tipo de dispositivo"
    )
    icon = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Emoji o ícono para mostrar (ej: 💡, 🌡️, 🔌)"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Orden de visualización (menor número = más arriba)"
    )
    guest_accessible = models.BooleanField(
        default=True,
        help_text="¿Los huéspedes pueden controlar este dispositivo?"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="¿Este dispositivo está activo?"
    )
    device_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Configuración adicional específica del tipo de dispositivo"
    )
    description = models.TextField(
        null=True,
        blank=True,
        help_text="Descripción o instrucciones para el huésped"
    )
    requires_temperature_pool = models.BooleanField(
        default=False,
        help_text="Solo mostrar este dispositivo si la reserva activa tiene temperature_pool=True (ej: calefacción de piscina)"
    )
    status_sensor_entity_id = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Entity ID de un sensor opcional para mostrar el estado real del dispositivo (ej: binary_sensor.garage_door_contact)"
    )

    class Meta:
        ordering = ['property', 'display_order', 'friendly_name']
        verbose_name = "Dispositivo de Home Assistant"
        verbose_name_plural = "Dispositivos de Home Assistant"
        unique_together = ('property', 'entity_id')
    
    def __str__(self):
        return f"{self.property.name} - {self.icon or ''} {self.friendly_name}"
    
    def get_icon_display(self):
        """Retorna el ícono o un ícono por defecto según el tipo"""
        if self.icon:
            return self.icon
        
        icon_map = {
            self.DeviceType.LIGHT: "💡",
            self.DeviceType.CLIMATE: "🌡️",
            self.DeviceType.SWITCH: "🔌",
            self.DeviceType.COVER: "🪟",
            self.DeviceType.SCENE: "🎬",
            self.DeviceType.FAN: "🌀",
            self.DeviceType.MEDIA_PLAYER: "📺",
            self.DeviceType.LOCK: "🔒",
            self.DeviceType.CAMERA: "📷",
            self.DeviceType.SENSOR: "📡",
        }
        return icon_map.get(self.device_type, "🔧")
