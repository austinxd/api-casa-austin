from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Event, EventRegistration, ActivityFeed
import logging

logger = logging.getLogger(__name__)


# Variable global para almacenar estado anterior del evento
_event_previous_status = {}


@receiver(pre_save, sender=Event)
def capture_event_previous_status(sender, instance, **kwargs):
    """
    Capturar el estado anterior del evento antes de guardarlo
    """
    if instance.pk:
        try:
            old_event = Event.objects.get(pk=instance.pk)
            _event_previous_status[instance.pk] = old_event.status
        except Event.DoesNotExist:
            _event_previous_status[instance.pk] = None
    else:
        _event_previous_status[instance.pk] = None


@receiver(post_save, sender=Event)
def create_event_activity(sender, instance, created, **kwargs):
    """
    Crear actividad cuando se publica un evento por primera vez
    """
    try:
        # Solo crear actividad si:
        # 1. Es un evento nuevo (created=True) Y status es PUBLISHED
        # 2. O si cambió de otro status a PUBLISHED
        
        should_create_activity = False
        
        if created and instance.status == Event.EventStatus.PUBLISHED:
            # Evento nuevo ya publicado
            should_create_activity = True
            logger.debug(f"Nuevo evento publicado: {instance.title}")
            
        elif not created:
            # Evento existente - verificar si cambió a PUBLISHED
            previous_status = _event_previous_status.get(instance.pk)
            if previous_status and previous_status != Event.EventStatus.PUBLISHED and instance.status == Event.EventStatus.PUBLISHED:
                should_create_activity = True
                logger.debug(f"Evento cambió a publicado: {instance.title} (anterior: {previous_status})")
            
            # Limpiar el estado anterior almacenado
            _event_previous_status.pop(instance.pk, None)
        
        if should_create_activity and instance.is_active and instance.is_public:
            # Verificar que no exista ya una actividad de creación para este evento
            existing_activity = ActivityFeed.objects.filter(
                activity_type=ActivityFeed.ActivityType.EVENT_CREATED,
                event=instance,
                deleted=False
            ).exists()
            
            if not existing_activity:
                ActivityFeed.create_activity(
                    activity_type=ActivityFeed.ActivityType.EVENT_CREATED,
                    event=instance,
                    property_location=instance.property_location,
                    activity_data={
                        'event_name': instance.title,
                        'event_id': str(instance.id),
                        'event_date': instance.event_date.isoformat(),
                        'registration_deadline': instance.registration_deadline.isoformat(),
                        'category': instance.category.name if instance.category else 'General',
                        'location': instance.location or '',
                        'max_participants': instance.max_participants,
                        'min_points_required': float(instance.min_points_required) if instance.min_points_required else 0
                    },
                    importance_level=3  # Alta - eventos nuevos son importantes
                )
                logger.info(f"Actividad de evento creado: {instance.title}")
            else:
                logger.debug(f"Actividad ya existe para evento: {instance.title}")
                
    except Exception as e:
        logger.error(f"Error creando actividad para evento {instance.id}: {str(e)}")


@receiver(post_save, sender=EventRegistration)
def create_winner_activity(sender, instance, created, **kwargs):
    """
    Crear actividad cuando alguien gana un evento
    """
    try:
        # Solo procesar si no es nuevo registro y ahora es ganador
        if not created and instance.winner_status != EventRegistration.WinnerStatus.NOT_WINNER:
            
            # Verificar que no exista ya una actividad de ganador para este registro
            existing_activity = ActivityFeed.objects.filter(
                activity_type=ActivityFeed.ActivityType.EVENT_WINNER,
                client=instance.client,
                event=instance.event,
                activity_data__registration_id=str(instance.id),
                deleted=False
            ).exists()
            
            if not existing_activity:
                # Determinar posición
                position_map = {
                    EventRegistration.WinnerStatus.WINNER: "🏆 ganador",
                    EventRegistration.WinnerStatus.RUNNER_UP: "🥈 segundo lugar", 
                    EventRegistration.WinnerStatus.THIRD_PLACE: "🥉 tercer lugar"
                }
                
                position = position_map.get(instance.winner_status, "ganador")
                
                ActivityFeed.create_activity(
                    activity_type=ActivityFeed.ActivityType.EVENT_WINNER,
                    client=instance.client,
                    event=instance.event,
                    property_location=instance.event.property_location,
                    activity_data={
                        'event_name': instance.event.title,
                        'event_id': str(instance.event.id),
                        'registration_id': str(instance.id),
                        'position': position,
                        'prize': instance.prize_description or '',
                        'winner_announcement_date': instance.winner_announcement_date.isoformat() if instance.winner_announcement_date else timezone.now().isoformat(),
                        'category': instance.event.category.name if instance.event.category else 'General'
                    },
                    importance_level=4  # Crítica - ganadores son muy importantes
                )
                logger.info(f"Actividad de ganador creada: {instance.client.first_name} ganó {instance.event.title}")
            else:
                logger.debug(f"Actividad de ganador ya existe para: {instance.client.first_name} - {instance.event.title}")
                
    except Exception as e:
        logger.error(f"Error creando actividad de ganador para registro {instance.id}: {str(e)}")