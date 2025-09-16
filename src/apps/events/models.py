from django.db import models
from apps.core.models import BaseModel
from apps.clients.models import Clients, Achievement
import os
from PIL import Image
from django.core.files.base import ContentFile
from io import BytesIO


class EventCategory(BaseModel):
    """Categorías de eventos: Sorteo, Concurso, Fiesta Privada, etc."""
    
    name = models.CharField(max_length=100, help_text="Nombre de la categoría (ej: Sorteo, Concurso)")
    description = models.TextField(blank=True, help_text="Descripción de la categoría")
    icon = models.CharField(max_length=10, blank=True, help_text="Emoji o icono representativo")
    color = models.CharField(max_length=7, default="#007bff", help_text="Color en formato hex (#000000)")
    
    class Meta:
        verbose_name = "Categoría de Evento"
        verbose_name_plural = "Categorías de Eventos"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.icon} {self.name}" if self.icon else self.name


class Event(BaseModel):
    """Eventos individuales con restricciones específicas"""
    
    class EventStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicado"
        CLOSED = "closed", "Cerrado"
        CANCELLED = "cancelled", "Cancelado"
    
    # Información básica
    title = models.CharField(max_length=200, help_text="Título del evento")
    description = models.TextField(help_text="Descripción detallada del evento")
    category = models.ForeignKey(EventCategory, on_delete=models.CASCADE, related_name='events')
    image = models.ImageField(upload_to='events/', blank=True, null=True, help_text="Imagen del evento (se convertirá automáticamente a WebP)")
    
    # Fechas y ubicación
    start_date = models.DateTimeField(help_text="Fecha y hora de inicio")
    end_date = models.DateTimeField(help_text="Fecha y hora de fin")
    registration_deadline = models.DateTimeField(blank=True, null=True, help_text="Fecha límite para registrarse")
    location = models.CharField(max_length=300, blank=True, help_text="Ubicación del evento")
    
    # Configuración
    max_participants = models.PositiveIntegerField(blank=True, null=True, help_text="Máximo número de participantes")
    is_public = models.BooleanField(default=True, help_text="Mostrar en listado público")
    is_active = models.BooleanField(default=True, help_text="Evento activo")
    status = models.CharField(max_length=10, choices=EventStatus.choices, default=EventStatus.DRAFT)
    
    # Restricciones específicas por evento
    required_achievements = models.ManyToManyField(
        Achievement, 
        blank=True, 
        help_text="Logros requeridos para registrarse (cliente debe tener AL MENOS UNO)"
    )
    min_points_required = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0, 
        help_text="Puntos mínimos requeridos para registrarse"
    )
    
    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"
        ordering = ['-start_date']
    
    def __str__(self):
        return f"{self.title} - {self.start_date.strftime('%d/%m/%Y')}"
    
    def can_register(self):
        """Verifica si el evento permite registros"""
        from django.utils import timezone
        now = timezone.now()
        
        if not self.is_active or self.status != self.EventStatus.PUBLISHED:
            return False, "Evento no disponible"
        
        if self.registration_deadline and now > self.registration_deadline:
            return False, "Fecha límite de registro expirada"
        
        if self.max_participants:
            registered_count = self.registrations.filter(status='approved').count()
            if registered_count >= self.max_participants:
                return False, "Evento lleno"
        
        return True, "Disponible"
    
    def client_can_register(self, client):
        """Verifica si un cliente específico puede registrarse"""
        
        # Verificar si el evento permite registros en general
        can_register, message = self.can_register()
        if not can_register:
            return False, message
        
        # Verificar si ya está registrado
        if self.registrations.filter(client=client).exists():
            return False, "Ya estás registrado en este evento"
        
        # Verificar puntos mínimos
        if self.min_points_required > 0:
            if client.points_balance < self.min_points_required:
                return False, f"Necesitas al menos {self.min_points_required} puntos"
        
        # Verificar logros requeridos
        if self.required_achievements.exists():
            client_achievements = client.achievements.all()
            required_achievements = self.required_achievements.all()
            
            if not any(achievement in client_achievements for achievement in required_achievements):
                achievement_names = [str(achievement) for achievement in required_achievements]
                return False, f"Necesitas uno de estos logros: {', '.join(achievement_names)}"
        
        return True, "Puedes registrarte"
    
    @property
    def registered_count(self):
        """Número de participantes registrados aprobados"""
        return self.registrations.filter(status='approved').count()
    
    def save(self, *args, **kwargs):
        """Convertir imagen a WebP automáticamente al guardar"""
        if self.image:
            self.image = self._convert_to_webp(self.image)
        super().save(*args, **kwargs)
    
    def _convert_to_webp(self, image_field):
        """Convierte la imagen a formato WebP"""
        try:
            # Abrir la imagen
            image = Image.open(image_field)
            
            # Convertir a RGB si es necesario (WebP no soporta transparencia en modo P)
            if image.mode in ('RGBA', 'LA', 'P'):
                image = image.convert('RGB')
            
            # Crear buffer para la imagen WebP
            webp_buffer = BytesIO()
            
            # Guardar como WebP con calidad optimizada
            image.save(webp_buffer, format='WebP', quality=85, optimize=True)
            webp_buffer.seek(0)
            
            # Generar nuevo nombre de archivo
            original_name = os.path.splitext(image_field.name)[0]
            webp_name = f"{original_name}.webp"
            
            # Crear nuevo ContentFile
            return ContentFile(webp_buffer.getvalue(), name=webp_name)
            
        except Exception as e:
            # Si hay error, retornar imagen original
            print(f"Error convirtiendo imagen a WebP: {e}")
            return image_field

    @property
    def available_spots(self):
        """Cupos disponibles"""
        if not self.max_participants:
            return None
        return self.max_participants - self.registered_count


class EventRegistration(BaseModel):
    """Registro de clientes a eventos"""
    
    class RegistrationStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobado"
        REJECTED = "rejected", "Rechazado"
        CANCELLED = "cancelled", "Cancelado"
    
    class WinnerStatus(models.TextChoices):
        NOT_WINNER = "not_winner", "No ganador"
        WINNER = "winner", "🏆 Ganador"
        RUNNER_UP = "runner_up", "🥈 Segundo lugar"
        THIRD_PLACE = "third_place", "🥉 Tercer lugar"
    
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='event_registrations')
    status = models.CharField(max_length=10, choices=RegistrationStatus.choices, default=RegistrationStatus.PENDING)
    registration_date = models.DateTimeField(auto_now_add=True)
    
    # Información adicional
    notes = models.TextField(blank=True, help_text="Notas del registro")
    admin_notes = models.TextField(blank=True, help_text="Notas del administrador")
    
    # 🏆 SISTEMA DE GANADORES
    winner_status = models.CharField(
        max_length=15, 
        choices=WinnerStatus.choices, 
        default=WinnerStatus.NOT_WINNER,
        help_text="Estado del participante en el evento"
    )
    winner_announcement_date = models.DateTimeField(
        blank=True, 
        null=True, 
        help_text="Fecha cuando se anunció como ganador"
    )
    prize_description = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Descripción del premio ganado"
    )
    winner_notified = models.BooleanField(
        default=False, 
        help_text="Si el ganador fue notificado por WhatsApp"
    )
    
    class Meta:
        verbose_name = "Registro de Evento"
        verbose_name_plural = "Registros de Eventos"
        unique_together = ('event', 'client')  # Un cliente solo puede registrarse una vez por evento
        ordering = ['-registration_date']
    
    def __str__(self):
        winner_emoji = ""
        if self.winner_status == self.WinnerStatus.WINNER:
            winner_emoji = "🏆 "
        elif self.winner_status == self.WinnerStatus.RUNNER_UP:
            winner_emoji = "🥈 "
        elif self.winner_status == self.WinnerStatus.THIRD_PLACE:
            winner_emoji = "🥉 "
            
        return f"{winner_emoji}{self.client.first_name} - {self.event.title} ({self.status})"
    
    @property
    def is_winner(self):
        """Verifica si este registro es ganador (cualquier posición)"""
        return self.winner_status != self.WinnerStatus.NOT_WINNER
    
    def mark_as_winner(self, winner_status, prize_description="", notify=True):
        """Marcar como ganador y opcionalmente notificar"""
        from django.utils import timezone
        
        self.winner_status = winner_status
        self.winner_announcement_date = timezone.now()
        if prize_description:
            self.prize_description = prize_description
        
        # Notificar por WhatsApp si se requiere
        if notify and not self.winner_notified:
            self._notify_winner()
        
        self.save()
    
    def _notify_winner(self):
        """Notificar ganador por WhatsApp"""
        try:
            from apps.clients.whatsapp_service import WhatsAppService
            
            # Determinar mensaje según posición
            if self.winner_status == self.WinnerStatus.WINNER:
                template = "ganador_primer_lugar"
            elif self.winner_status == self.WinnerStatus.RUNNER_UP:
                template = "ganador_segundo_lugar"
            elif self.winner_status == self.WinnerStatus.THIRD_PLACE:
                template = "ganador_tercer_lugar"
            else:
                return
            
            # Enviar notificación
            WhatsAppService.send_template_message(
                to_phone=self.client.phone,
                template_name=template,
                parameters={
                    'client_name': self.client.first_name,
                    'event_title': self.event.title,
                    'prize': self.prize_description or "Premio especial"
                }
            )
            
            self.winner_notified = True
            self.save(update_fields=['winner_notified'])
            
        except Exception as e:
            print(f"Error notificando ganador: {e}")