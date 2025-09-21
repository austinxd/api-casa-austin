from django.db import models
from apps.core.models import BaseModel
from apps.clients.models import Clients, Achievement
from apps.property.models import Property
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
    thumbnail = models.ImageField(upload_to='events/thumbnails/', blank=True, null=True, help_text="Miniatura del evento (generada automáticamente)")
    
    # Fechas y ubicación
    event_date = models.DateTimeField(help_text="Fecha y hora del sorteo/evento")
    registration_deadline = models.DateTimeField(help_text="Fecha límite para registrarse")
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
    
    # 🏠 Propiedad asociada (para sorteos de estadías)
    property_location = models.ForeignKey(
        Property,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text="Propiedad asociada (solo para sorteos de estadías/noches gratis)",
        verbose_name="Propiedad"
    )
    
    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"
        ordering = ['-event_date']
    
    def __str__(self):
        return f"{self.title} - {self.event_date.strftime('%d/%m/%Y')}"
    
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
        
        # Verificar si ya está registrado (solo registros activos, no cancelados)
        if self.registrations.filter(
            client=client,
            deleted=False,
            status__in=['pending', 'approved']
        ).exists():
            return False, "Ya estás registrado en este evento"
        
        # Verificar puntos mínimos
        if self.min_points_required > 0:
            if client.points_balance < self.min_points_required:
                return False, f"Necesitas al menos {self.min_points_required} puntos"
        
        # Verificar logros requeridos
        if self.required_achievements.exists():
            # AUTO-ASIGNACIÓN: Verificar y asignar achievements automáticamente antes de validar
            from apps.clients.signals import check_and_assign_achievements
            try:
                check_and_assign_achievements(client)
            except Exception:
                pass  # Si falla la auto-asignación, continuar con validación normal
            
            # Refrescar achievements después de la auto-asignación
            client_achievements = client.achievements.filter(deleted=False).values_list('achievement', flat=True)
            required_achievement_ids = self.required_achievements.values_list('id', flat=True)
            
            if not any(req_id in client_achievements for req_id in required_achievement_ids):
                achievement_names = [str(achievement) for achievement in self.required_achievements.all()]
                return False, f"Necesitas uno de estos logros: {', '.join(achievement_names)}"
        
        return True, "Puedes registrarte"
    
    @property
    def registered_count(self):
        """Número de participantes registrados aprobados"""
        return self.registrations.filter(status='approved').count()
    
    def save(self, *args, **kwargs):
        """Convertir imagen a WebP y generar thumbnail automáticamente al guardar"""
        if self.image:
            # Verificar si la imagen cambió
            imagen_cambio = False
            if self.pk:
                try:
                    original = Event.objects.get(pk=self.pk)
                    imagen_cambio = str(original.image) != str(self.image)
                except Event.DoesNotExist:
                    imagen_cambio = True
            else:
                imagen_cambio = True
            
            if imagen_cambio:
                self.image = self._convert_to_webp(self.image)
                # Regenerar thumbnail cuando la imagen cambia
                self.thumbnail = self._create_thumbnail(self.image)
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
            
            # Generar nuevo nombre de archivo (solo basename para evitar rutas duplicadas)
            original_basename = os.path.basename(image_field.name)
            name_without_ext = os.path.splitext(original_basename)[0]
            webp_name = f"{name_without_ext}.webp"
            
            # Crear nuevo ContentFile
            return ContentFile(webp_buffer.getvalue(), name=webp_name)
            
        except Exception as e:
            # Si hay error, retornar imagen original
            print(f"Error convirtiendo imagen a WebP: {e}")
            return image_field
    
    def _create_thumbnail(self, image_field, size=(300, 200)):
        """Crear thumbnail optimizado de la imagen"""
        try:
            # Abrir la imagen
            image = Image.open(image_field)
            
            # Convertir a RGB si es necesario
            if image.mode in ('RGBA', 'LA', 'P'):
                image = image.convert('RGB')
            
            # Crear thumbnail manteniendo proporción
            image.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Crear buffer para el thumbnail
            thumb_buffer = BytesIO()
            
            # Guardar como WebP con calidad optimizada para thumbnail
            image.save(thumb_buffer, format='WebP', quality=75, optimize=True)
            thumb_buffer.seek(0)
            
            # Generar nombre para el thumbnail (solo basename para evitar rutas duplicadas)
            original_basename = os.path.basename(image_field.name)
            name_without_ext = os.path.splitext(original_basename)[0]
            thumb_name = f"{name_without_ext}_thumb.webp"
            
            # Crear ContentFile para el thumbnail
            return ContentFile(thumb_buffer.getvalue(), name=thumb_name)
            
        except Exception as e:
            print(f"Error creando thumbnail: {e}")
            return None

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


class ActivityFeed(BaseModel):
    """Feed de actividades de Casa Austin - Últimos acontecimientos del sistema"""
    
    class ActivityType(models.TextChoices):
        POINTS_EARNED = "points_earned", "Puntos Ganados"
        RESERVATION_MADE = "reservation_made", "Reserva Realizada"
        RESERVATION_AUTO_DELETED_CRON = "reservation_auto_deleted_cron", "Reserva Eliminada por Sistema"
        CLIENT_REGISTERED = "client_registered", "Cliente Registrado"
        EVENT_CREATED = "event_created", "Evento Creado"
        EVENT_REGISTRATION = "event_registration", "Registro a Evento"
        EVENT_WINNER = "event_winner", "Ganador de Evento"
        ACHIEVEMENT_EARNED = "achievement_earned", "Logro Obtenido"
        PAYMENT_COMPLETED = "payment_completed", "Pago Completado"
        DISCOUNT_USED = "discount_used", "Descuento Utilizado"
        REVIEW_POSTED = "review_posted", "Reseña Publicada"
        STAFF_ASSIGNED = "staff_assigned", "Personal Asignado"
        MILESTONE_REACHED = "milestone_reached", "Hito Alcanzado"
        SYSTEM_UPDATE = "system_update", "Actualización del Sistema"
    
    # Información básica de la actividad
    activity_type = models.CharField(
        max_length=35, 
        choices=ActivityType.choices,
        help_text="Tipo de actividad registrada"
    )
    title = models.CharField(
        max_length=200, 
        help_text="Título descriptivo de la actividad"
    )
    description = models.TextField(
        blank=True,
        help_text="Descripción detallada opcional"
    )
    
    # Relaciones opcionales (dependiendo del tipo de actividad)
    client = models.ForeignKey(
        Clients,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activities',
        help_text="Cliente relacionado con la actividad (opcional)"
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activities',
        help_text="Evento relacionado con la actividad (opcional)"
    )
    property_location = models.ForeignKey(
        Property,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activities',
        help_text="Propiedad relacionada con la actividad (opcional)"
    )
    
    # Datos específicos de la actividad (JSON flexible)
    activity_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Datos específicos de la actividad en formato JSON"
    )
    
    # Metadatos
    is_public = models.BooleanField(
        default=True,
        help_text="Si la actividad debe mostrarse en el feed público"
    )
    icon = models.CharField(
        max_length=10, 
        blank=True,
        help_text="Emoji o icono representativo de la actividad"
    )
    importance_level = models.PositiveSmallIntegerField(
        default=1,
        help_text="Nivel de importancia (1=baja, 2=media, 3=alta, 4=crítica)"
    )
    
    class Meta:
        verbose_name = "Actividad del Feed"
        verbose_name_plural = "Actividades del Feed"
        ordering = ['-created']  # Más recientes primero
        indexes = [
            models.Index(fields=['activity_type', 'created']),
            models.Index(fields=['client', 'created']),
            models.Index(fields=['is_public', 'created']),
        ]
    
    def __str__(self):
        if self.client:
            return f"{self.get_activity_type_display()}: {self.client.first_name} - {self.title}"
        return f"{self.get_activity_type_display()}: {self.title}"
    
    def get_formatted_message(self):
        """Genera mensaje formateado automáticamente según el tipo de actividad"""
        
        # Nombre del cliente con formato de privacidad
        client_name = self.format_client_name_private(self.client) or ""
        
        # Formatear según tipo de actividad
        if self.activity_type == self.ActivityType.POINTS_EARNED:
            points = self.activity_data.get('points', 0)
            reason = self.activity_data.get('reason', 'una actividad')
            property_name = self.activity_data.get('property_name', 'Casa Austin')
            return f"{client_name} acaba de ganar {points} puntos por {reason} en {property_name}"
        
        elif self.activity_type == self.ActivityType.RESERVATION_MADE:
            property_name = self.activity_data.get('property_name', 'Casa Austin')
            dates = self.activity_data.get('dates', '')
            status_change = self.activity_data.get('status_change', '')
            
            if status_change == 'cancelled':
                return f"{client_name} canceló su reserva {dates} en {property_name}"
            else:
                return f"{client_name} hizo una reserva {dates} en {property_name}"
        
        elif self.activity_type == self.ActivityType.PAYMENT_COMPLETED:
            property_name = self.activity_data.get('property_name', 'Casa Austin')
            dates = self.activity_data.get('dates', '')
            status_change = self.activity_data.get('status_change', '')
            
            # No incluir iconos si ya existe uno en el campo icon
            check_icon = "✅ " if not self.icon else ""
            money_icon = "💰 " if not self.icon else ""
            
            if status_change == 'approved_by_admin':
                return f"{check_icon}Reserva de {client_name} fue aprobada {dates} en {property_name}"
            else:
                return f"{money_icon}{client_name} completó el pago de su reserva {dates} en {property_name}"
        
        elif self.activity_type == self.ActivityType.RESERVATION_AUTO_DELETED_CRON:
            property_name = self.activity_data.get('property_name', 'una propiedad')
            dates = self.activity_data.get('dates', '')
            reason = self.activity_data.get('reason', 'inactividad')
            reservation_id = self.activity_data.get('reservation_id', '')
            
            # No incluir icono si ya existe uno en el campo icon
            clock_icon = "⏰ " if not self.icon else ""
            
            if client_name:
                return f"{clock_icon}El sistema eliminó la reserva de {client_name} {dates} en {property_name} por {reason}"
            else:
                return f"{clock_icon}El sistema eliminó una reserva {dates} en {property_name} por {reason}"
        
        elif self.activity_type == self.ActivityType.CLIENT_REGISTERED:
            referred_by_info = self.activity_data.get('referred_by_info')
            
            # No incluir icono si ya existe uno en el campo icon
            user_icon = "👤 " if not self.icon else ""
            
            if referred_by_info:
                # Cliente fue referido - mensaje completo con información de puntos
                referrer_name = referred_by_info.get('name', 'alguien')
                points_percentage = referred_by_info.get('points_percentage', 10.0)
                
                if client_name:
                    return f"{user_icon}{client_name} se acaba de registrar y fue referido por {referrer_name}, quien ganará {points_percentage}% de puntos por cada reserva que realice"
                else:
                    return f"{user_icon}Se registró un nuevo cliente referido por {referrer_name}, quien ganará {points_percentage}% de puntos por cada reserva"
            else:
                # Cliente normal sin referido
                if client_name:
                    return f"{user_icon}Se registró un nuevo cliente: {client_name}"
                else:
                    return f"{user_icon}Se registró un nuevo cliente"
        
        elif self.activity_type == self.ActivityType.EVENT_CREATED:
            event_name = self.event.title if self.event else self.activity_data.get('event_name', 'un evento')
            return f"¡Nuevo evento creado! {event_name}"
        
        elif self.activity_type == self.ActivityType.EVENT_REGISTRATION:
            event_name = self.event.title if self.event else self.activity_data.get('event_name', 'un evento')
            return f"{client_name} se registró para el evento: {event_name}"
        
        elif self.activity_type == self.ActivityType.EVENT_WINNER:
            event_name = self.event.title if self.event else self.activity_data.get('event_name', 'un evento')
            position = self.activity_data.get('position', 'ganador')
            prize = self.activity_data.get('prize', '')
            prize_text = f" - {prize}" if prize else ""
            
            # No incluir icono si ya existe uno en el campo icon
            trophy_icon = "🏆 " if not self.icon else ""
            
            return f"{trophy_icon}{client_name} es {position} del evento: {event_name}{prize_text}"
        
        elif self.activity_type == self.ActivityType.ACHIEVEMENT_EARNED:
            achievement_name = self.activity_data.get('achievement_name', 'un logro')
            
            # No incluir icono si ya existe uno en el campo icon
            if not self.icon:
                achievement_icon = self.activity_data.get('achievement_icon', '🏅')
                return f"{achievement_icon} {client_name} obtuvo el logro: {achievement_name}"
            else:
                return f"{client_name} obtuvo el logro: {achievement_name}"
        
        elif self.activity_type == self.ActivityType.DISCOUNT_USED:
            discount_name = self.activity_data.get('discount_name', 'un descuento')
            return f"{client_name} usó {discount_name}"
        
        elif self.activity_type == self.ActivityType.MILESTONE_REACHED:
            milestone = self.activity_data.get('milestone', 'un hito importante')
            
            # No incluir icono si ya existe uno en el campo icon
            party_icon = "🎉 " if not self.icon else ""
            
            return f"{party_icon}¡Casa Austin alcanzó {milestone}!"
        
        elif self.activity_type == self.ActivityType.SYSTEM_UPDATE:
            update_name = self.activity_data.get('update_name', 'una actualización')
            
            # No incluir icono si ya existe uno en el campo icon
            speaker_icon = "📢 " if not self.icon else ""
            
            return f"{speaker_icon}{update_name}"
        
        # Fallback a título personalizado si existe
        return self.title if self.title else f"Nueva actividad: {self.get_activity_type_display()}"
    
    def get_icon(self):
        """Obtiene icono automático según tipo de actividad"""
        if self.icon:
            return self.icon
        
        icon_map = {
            self.ActivityType.POINTS_EARNED: "⭐",
            self.ActivityType.RESERVATION_MADE: "📅",
            self.ActivityType.EVENT_CREATED: "🎉",
            self.ActivityType.EVENT_REGISTRATION: "✅",
            self.ActivityType.EVENT_WINNER: "🏆",
            self.ActivityType.ACHIEVEMENT_EARNED: "🏅",
            self.ActivityType.PAYMENT_COMPLETED: "💰",
            self.ActivityType.DISCOUNT_USED: "🎫",
            self.ActivityType.REVIEW_POSTED: "📝",
            self.ActivityType.STAFF_ASSIGNED: "👥",
            self.ActivityType.MILESTONE_REACHED: "🎯",
            self.ActivityType.SYSTEM_UPDATE: "📢"
        }
        
        return icon_map.get(self.activity_type, "📌")
    
    @property
    def time_ago(self):
        """Tiempo transcurrido desde la actividad"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - self.created
        
        if diff < timedelta(minutes=1):
            return "hace un momento"
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f"hace {minutes} minuto{'s' if minutes != 1 else ''}"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"hace {hours} hora{'s' if hours != 1 else ''}"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"hace {days} día{'s' if days != 1 else ''}"
        else:
            return self.created.strftime('%d/%m/%Y')
    
    @staticmethod
    def format_client_name_private(client):
        """
        Formatea el nombre del cliente para privacidad: 'Primer Nombre + Inicial'
        Ejemplo: 'Augusto T.' en lugar de 'Augusto Torres'
        """
        if not client:
            return None
        
        # Obtener solo el primer nombre (dividir por espacios y tomar el primero)
        full_first_name = client.first_name or "Usuario"
        first_name_only = full_first_name.strip().split()[0] if full_first_name.strip() else "Usuario"
        
        # Agregar inicial del apellido si existe
        if client.last_name and client.last_name.strip():
            last_initial = client.last_name.strip()[0].upper()
            return f"{first_name_only} {last_initial}."
        
        return first_name_only
    
    @classmethod
    def create_activity(cls, activity_type, title=None, client=None, event=None, 
                       property_location=None, activity_data=None, **kwargs):
        """Método helper para crear actividades fácilmente"""
        
        activity_data = activity_data or {}
        
        # Auto-generar título si no se proporciona
        if not title:
            title = cls._generate_simple_title(activity_type)
        
        return cls.objects.create(
            activity_type=activity_type,
            title=title,
            client=client,
            event=event,
            property_location=property_location,
            activity_data=activity_data,
            **kwargs
        )
    
    @classmethod
    def _generate_simple_title(cls, activity_type):
        """Genera títulos simples y descriptivos para cada tipo de actividad"""
        title_map = {
            cls.ActivityType.POINTS_EARNED: "Puntos Ganados",
            cls.ActivityType.RESERVATION_MADE: "Nueva Reserva",
            cls.ActivityType.RESERVATION_AUTO_DELETED_CRON: "Reserva Expirada",
            cls.ActivityType.CLIENT_REGISTERED: "Nuevo Cliente",
            cls.ActivityType.EVENT_CREATED: "Evento Creado",
            cls.ActivityType.EVENT_REGISTRATION: "Registro a Evento",
            cls.ActivityType.EVENT_WINNER: "Ganador de Evento",
            cls.ActivityType.ACHIEVEMENT_EARNED: "Logro Obtenido",
            cls.ActivityType.PAYMENT_COMPLETED: "Pago Completado",
            cls.ActivityType.DISCOUNT_USED: "Descuento Aplicado",
            cls.ActivityType.REVIEW_POSTED: "Reseña Publicada",
            cls.ActivityType.STAFF_ASSIGNED: "Personal Asignado",
            cls.ActivityType.MILESTONE_REACHED: "Hito Alcanzado",
            cls.ActivityType.SYSTEM_UPDATE: "Actualización del Sistema"
        }
        return title_map.get(activity_type, "Actividad Registrada")


class ActivityFeedConfig(BaseModel):
    """
    Configuración global del Feed de Actividades
    Permite controlar qué tipos de actividades aparecen automáticamente
    """
    
    # Tipo de actividad a configurar
    activity_type = models.CharField(
        max_length=35,
        choices=ActivityFeed.ActivityType.choices,
        unique=True,
        help_text="Tipo de actividad a configurar"
    )
    
    # Configuraciones
    is_enabled = models.BooleanField(
        default=True,
        help_text="¿Permitir que se generen automáticamente actividades de este tipo?"
    )
    
    is_public_by_default = models.BooleanField(
        default=True,
        help_text="¿Las actividades de este tipo deben ser públicas por defecto?"
    )
    
    default_importance_level = models.IntegerField(
        default=2,
        choices=[(1, 'Muy Baja'), (2, 'Baja'), (3, 'Media'), (4, 'Alta'), (5, 'Crítica')],
        help_text="Nivel de importancia por defecto para este tipo"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Descripción de qué incluye este tipo de actividad"
    )
    
    class Meta:
        verbose_name = "Configuración de Feed de Actividades"
        verbose_name_plural = "Configuraciones de Feed de Actividades"
        ordering = ['activity_type']
    
    def __str__(self):
        status = "✅ Habilitado" if self.is_enabled else "❌ Deshabilitado"
        visibility = "🌐 Público" if self.is_public_by_default else "🔒 Privado"
        return f"{self.get_activity_type_display()} - {status} ({visibility})"
    
    @classmethod
    def is_type_enabled(cls, activity_type):
        """Verificar si un tipo de actividad está habilitado"""
        try:
            config = cls.objects.get(activity_type=activity_type)
            return config.is_enabled
        except cls.DoesNotExist:
            # Si no hay configuración, está habilitado por defecto
            return True
    
    @classmethod
    def should_be_public(cls, activity_type):
        """Verificar si un tipo de actividad debe ser público por defecto"""
        try:
            config = cls.objects.get(activity_type=activity_type)
            return config.is_public_by_default
        except cls.DoesNotExist:
            # Si no hay configuración, es público por defecto
            return True
    
    @classmethod
    def get_default_importance(cls, activity_type):
        """Obtener el nivel de importancia por defecto para un tipo"""
        try:
            config = cls.objects.get(activity_type=activity_type)
            return config.default_importance_level
        except cls.DoesNotExist:
            # Si no hay configuración, usar importancia media
            return 2