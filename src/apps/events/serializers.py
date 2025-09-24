from rest_framework import serializers
from .models import EventCategory, Event, EventRegistration, ActivityFeed
from apps.clients.models import Achievement
from apps.property.models import Property


class EventCategorySerializer(serializers.ModelSerializer):
    """Serializer público para categorías de eventos"""
    
    class Meta:
        model = EventCategory
        fields = ['id', 'name', 'description', 'icon', 'color']


class AchievementBasicSerializer(serializers.ModelSerializer):
    """Serializer básico para logros requeridos"""
    
    class Meta:
        model = Achievement
        fields = ['id', 'name', 'description', 'icon']


class PropertyBasicSerializer(serializers.ModelSerializer):
    """Serializer básico para propiedades asociadas a eventos"""
    
    class Meta:
        model = Property
        fields = ['id', 'name', 'titulo', 'location', 'dormitorios', 'banos', 'capacity_max', 'precio_desde']


class EventListSerializer(serializers.ModelSerializer):
    """Serializer para listado público de eventos"""
    
    category = EventCategorySerializer(read_only=True)
    property = PropertyBasicSerializer(source='property_location', read_only=True)
    can_register_status = serializers.SerializerMethodField()
    registered_count = serializers.ReadOnlyField()
    available_spots = serializers.ReadOnlyField()
    event_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'description', 'category', 'property', 'image', 'thumbnail',
            'event_date', 'registration_deadline', 'location',
            'max_participants', 'registered_count', 'available_spots',
            'min_points_required', 'requires_facebook_verification', 'requires_evidence', 'can_register_status', 'event_status'
        ]
        read_only_fields = ['slug']
    
    def get_can_register_status(self, obj):
        """Estado general de si el evento permite registros"""
        can_register, message = obj.can_register()
        return {
            'can_register': can_register,
            'message': message
        }
    
    def get_event_status(self, obj):
        """Clasificar evento como: upcoming, past"""
        from django.utils import timezone
        now = timezone.now()
        
        if obj.event_date > now:
            return 'upcoming'  # Próximo
        else:
            return 'past'      # Pasado


class EventDetailSerializer(serializers.ModelSerializer):
    """Serializer detallado para vista específica de evento"""
    
    category = EventCategorySerializer(read_only=True)
    required_achievements = AchievementBasicSerializer(many=True, read_only=True)
    can_register_status = serializers.SerializerMethodField()
    client_can_register = serializers.SerializerMethodField()
    registered_count = serializers.ReadOnlyField()
    available_spots = serializers.ReadOnlyField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'description', 'category', 'image',
            'event_date', 'registration_deadline', 'location',
            'max_participants', 'registered_count', 'available_spots',
            'min_points_required', 'requires_facebook_verification', 'requires_evidence', 'required_achievements',
            'can_register_status', 'client_can_register'
        ]
        read_only_fields = ['slug']
    
    def get_can_register_status(self, obj):
        """Estado general de si el evento permite registros"""
        can_register, message = obj.can_register()
        return {
            'can_register': can_register,
            'message': message
        }
    
    def get_client_can_register(self, obj):
        """Verificar si el cliente autenticado puede registrarse"""
        request = self.context.get('request')
        if not request or not hasattr(request, 'client'):
            return None
        
        can_register, message = obj.client_can_register(request.client)
        return {
            'can_register': can_register,
            'message': message
        }


class EventRegistrationSerializer(serializers.ModelSerializer):
    """Serializer para registros de eventos"""
    
    class Meta:
        model = EventRegistration
        fields = [
            'id', 'event', 'client', 'status', 
            'registration_date', 'notes', 'evidence_image'
        ]
        read_only_fields = ['registration_date']
        
    def to_representation(self, instance):
        """Personalizar la representación para mostrar detalles del evento"""
        representation = super().to_representation(instance)
        # Mostrar detalles completos del evento en la lectura
        representation['event'] = EventListSerializer(instance.event).data
        # Agregar nombre del cliente
        representation['client_name'] = instance.client.first_name if instance.client else None
        return representation


class EventRegistrationCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear registros"""
    
    class Meta:
        model = EventRegistration
        fields = ['notes']
    
    def create(self, validated_data):
        # El evento y cliente se asignan en la vista
        validated_data['event'] = self.context['event']
        validated_data['client'] = self.context['client']
        return super().create(validated_data)


# 🏆 SERIALIZERS PARA GANADORES
class WinnerSerializer(serializers.ModelSerializer):
    """Serializer para mostrar ganadores de eventos"""
    
    client_name = serializers.SerializerMethodField()
    client_avatar = serializers.CharField(source='client.avatar', read_only=True)
    position_name = serializers.CharField(source='get_winner_status_display', read_only=True)
    
    class Meta:
        model = EventRegistration
        fields = [
            'id', 'client_name', 'client_avatar', 'winner_status', 'position_name',
            'winner_announcement_date', 'prize_description'
        ]
    
    def get_client_name(self, obj):
        """Formato: Solo Primer Nombre + Inicial del Apellido (ej: Juan C.)"""
        if not obj.client:
            return None
        
        # Obtener solo el primer nombre (antes del primer espacio)
        full_first_name = obj.client.first_name or "Usuario"
        first_name_only = full_first_name.strip().split()[0] if full_first_name.strip() else "Usuario"
        
        # Agregar inicial del apellido si existe
        if obj.client.last_name and obj.client.last_name.strip():
            last_initial = obj.client.last_name.strip()[0].upper()
            return f"{first_name_only} {last_initial}."
        
        return first_name_only


class EventWinnersSerializer(serializers.ModelSerializer):
    """Serializer para evento con sus ganadores"""
    
    category = EventCategorySerializer(read_only=True)
    winners = serializers.SerializerMethodField()
    total_winners = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'description', 'category', 'image',
            'event_date', 'location', 'winners', 'total_winners'
        ]
        read_only_fields = ['slug']
    
    def get_winners(self, obj):
        """Obtener lista de ganadores ordenada por fecha de anuncio"""
        winners_queryset = obj.registrations.filter(
            winner_status=EventRegistration.WinnerStatus.WINNER
        ).order_by('-winner_announcement_date')
        
        return WinnerSerializer(winners_queryset, many=True).data
    
    def get_total_winners(self, obj):
        """Contar total de ganadores"""
        return obj.registrations.filter(
            winner_status=EventRegistration.WinnerStatus.WINNER
        ).count()


# 👥 SERIALIZER PARA PARTICIPANTES
class EventParticipantSerializer(serializers.ModelSerializer):
    """Serializer para mostrar participantes de un evento con foto y nivel"""
    
    profile_picture = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    highest_level = serializers.SerializerMethodField()
    facebook_profile_picture = serializers.SerializerMethodField()
    
    class Meta:
        model = EventRegistration
        fields = [
            'id', 'profile_picture', 'facebook_profile_picture', 
            'display_name', 'highest_level', 'winner_status', 
            'registration_date'
        ]
    
    def get_profile_picture(self, obj):
        """Obtiene la URL de la foto de perfil del cliente"""
        # Solo foto de Facebook disponible - el modelo Clients no tiene campo de foto personalizada
        if obj.client.facebook_linked and obj.client.facebook_id:
            facebook_photo = obj.client.get_facebook_profile_picture()
            if facebook_photo:
                return facebook_photo
        
        # No hay campos de foto personalizada en el modelo Clients actualmente
        return None
    
    def get_facebook_profile_picture(self, obj):
        """URL de la foto de perfil de Facebook si está disponible"""
        if obj.client.facebook_linked and obj.client.facebook_id:
            return obj.client.get_facebook_profile_picture()
        return None
    
    def get_display_name(self, obj):
        """Formato: Solo Primer Nombre + Inicial del Primer Apellido (ej: Augusto T.)"""
        full_first_name = obj.client.first_name or "Usuario"
        
        # Extraer solo el primer nombre (antes del primer espacio)
        first_name_only = full_first_name.strip().split()[0] if full_first_name.strip() else "Usuario"
        
        if obj.client.last_name and obj.client.last_name.strip():
            # Solo la primera inicial del apellido
            last_initial = obj.client.last_name.strip()[0].upper()
            return f"{first_name_only} {last_initial}."
        
        return first_name_only
    
    def get_highest_level(self, obj):
        """Obtiene el nivel más alto del cliente con icono"""
        from apps.clients.models import ClientAchievement
        
        # Obtener el logro más alto basado en requisitos
        highest_achievement = ClientAchievement.objects.filter(
            client=obj.client,
            deleted=False
        ).select_related('achievement').order_by(
            '-achievement__required_reservations',
            '-achievement__required_referrals', 
            '-achievement__required_referral_reservations',
            '-earned_at'
        ).first()
        
        if highest_achievement:
            return {
                'name': highest_achievement.achievement.name,
                'icon': highest_achievement.achievement.icon or "🏅",
                'description': highest_achievement.achievement.description,
                'earned_at': highest_achievement.earned_at
            }
        
        # Si no tiene logros, mostrar nivel básico
        return {
            'name': 'Nuevo Cliente',
            'icon': '⭐',
            'description': 'Cliente recién registrado',
            'earned_at': obj.client.created
        }


# 📊 SERIALIZERS PARA ACTIVITY FEED
class ActivityFeedSerializer(serializers.ModelSerializer):
    """Serializer optimizado para el feed de actividades de Casa Austin"""
    
    icon = serializers.SerializerMethodField()  # Obtenido del ActivityFeedConfig
    time_ago = serializers.ReadOnlyField()
    client_name = serializers.SerializerMethodField()
    client_info = serializers.SerializerMethodField()  # ✅ Nueva información completa del cliente
    activity_type_display = serializers.CharField(source='get_activity_type_display', read_only=True)
    activity_data = serializers.SerializerMethodField()  # Incluir reason y formatted_message aquí
    
    class Meta:
        model = ActivityFeed
        fields = [
            'id', 'activity_type', 'activity_type_display', 'title', 'description',
            'icon', 'time_ago', 'client_name', 'client_info',  # ✅ Agregado client_info
            'importance_level', 'created', 'activity_data'
        ]
    
    def get_icon(self, obj):
        """Obtiene el icono del ActivityFeedConfig o fallback"""
        return obj.get_icon()
    
    def get_activity_data(self, obj):
        """Incluir reason y formatted_message dentro de activity_data"""
        data = obj.activity_data.copy() if obj.activity_data else {}
        
        # Agregar formatted_message a activity_data
        data['formatted_message'] = obj.get_formatted_message()
        
        # SIEMPRE usar reason del config admin (prioridad sobre activity_data existente)
        from .models import ActivityFeedConfig
        config_reason = ActivityFeedConfig.get_default_reason(obj.activity_type)
        if config_reason:
            data['reason'] = config_reason
        elif 'reason' not in data:
            # Solo usar fallback si no hay config admin Y no hay reason en activity_data
            data['reason'] = ''
        
        return data
    
    def get_client_name(self, obj):
        """Obtiene el nombre del cliente en formato: Primer Nombre + Inicial"""
        if not obj.client:
            return None
        
        full_first_name = obj.client.first_name or "Usuario"
        first_name_only = full_first_name.strip().split()[0] if full_first_name.strip() else "Usuario"
        
        if obj.client.last_name and obj.client.last_name.strip():
            last_initial = obj.client.last_name.strip()[0].upper()
            return f"{first_name_only} {last_initial}."
        
        return first_name_only
    
    def get_client_info(self, obj):
        """Obtiene información completa del cliente incluyendo Facebook"""
        if not obj.client:
            return None
        
        return {
            'id': str(obj.client.id),
            'name': self.get_client_name(obj),
            'facebook_linked': obj.client.facebook_linked,  # ✅ Facebook vinculado
            'facebook_profile_picture': obj.client.get_facebook_profile_picture()  # ✅ Foto de perfil
        }
    
    def to_representation(self, instance):
        """Personalizar la representación para omitir campos de cliente cuando son null"""
        representation = super().to_representation(instance)
        
        # Si no hay cliente, remover completamente los campos de cliente
        if not instance.client:
            representation.pop('client_name', None)
            representation.pop('client_info', None)
        
        return representation


class ActivityFeedCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear actividades (uso interno del sistema)"""
    
    class Meta:
        model = ActivityFeed
        fields = [
            'activity_type', 'title', 'description', 'client', 'event', 
            'property_location', 'activity_data', 'is_public', 'importance_level'
        ]
    
    def create(self, validated_data):
        """Crear actividad usando el método helper del modelo"""
        return ActivityFeed.create_activity(**validated_data)


class ActivityFeedFilterSerializer(serializers.Serializer):
    """Serializer para filtros del feed de actividades"""
    
    activity_type = serializers.ChoiceField(
        choices=ActivityFeed.ActivityType.choices,
        required=False,
        help_text="Filtrar por tipo de actividad"
    )
    client_id = serializers.UUIDField(
        required=False,
        help_text="Filtrar por cliente específico"
    )
    importance_level = serializers.ChoiceField(
        choices=[(1, 'Baja'), (2, 'Media'), (3, 'Alta'), (4, 'Crítica')],
        required=False,
        help_text="Filtrar por nivel de importancia"
    )
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Actividades desde esta fecha"
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="Actividades hasta esta fecha"
    )
    is_public = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Solo actividades públicas"
    )