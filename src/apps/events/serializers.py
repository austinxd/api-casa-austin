from rest_framework import serializers
from .models import EventCategory, Event, EventRegistration
from apps.clients.models import Achievement


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


class EventListSerializer(serializers.ModelSerializer):
    """Serializer para listado público de eventos"""
    
    category = EventCategorySerializer(read_only=True)
    can_register_status = serializers.SerializerMethodField()
    registered_count = serializers.ReadOnlyField()
    available_spots = serializers.ReadOnlyField()
    event_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'title', 'description', 'category', 'image',
            'start_date', 'end_date', 'registration_deadline', 'location',
            'max_participants', 'registered_count', 'available_spots',
            'min_points_required', 'can_register_status', 'event_status'
        ]
    
    def get_can_register_status(self, obj):
        """Estado general de si el evento permite registros"""
        can_register, message = obj.can_register()
        return {
            'can_register': can_register,
            'message': message
        }
    
    def get_event_status(self, obj):
        """Clasificar evento como: upcoming, ongoing, past"""
        from django.utils import timezone
        now = timezone.now()
        
        if obj.start_date > now:
            return 'upcoming'  # Próximo
        elif obj.start_date <= now <= obj.end_date:
            return 'ongoing'   # En curso
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
            'id', 'title', 'description', 'category', 'image',
            'start_date', 'end_date', 'registration_deadline', 'location',
            'max_participants', 'registered_count', 'available_spots',
            'min_points_required', 'required_achievements',
            'can_register_status', 'client_can_register'
        ]
    
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
    
    event = EventListSerializer(read_only=True)
    client_name = serializers.CharField(source='client.first_name', read_only=True)
    
    class Meta:
        model = EventRegistration
        fields = [
            'id', 'event', 'client_name', 'status', 
            'registration_date', 'notes'
        ]
        read_only_fields = ['registration_date']


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