from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.validators import UniqueTogetherValidator
from decimal import Decimal

from .models import Clients, MensajeFidelidad, TokenApiClients, ClientPoints, SearchTracking, Achievement, ClientAchievement


class MensajeFidelidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MensajeFidelidad
        fields = ["mensaje"]

class TokenApiClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenApiClients
        exclude = ["id", "created", "updated", "deleted"]

class ClientsSerializer(serializers.ModelSerializer):
    level_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Clients
        exclude = ["created", "updated", "deleted"]
        validators = [
            UniqueTogetherValidator(
                queryset=Clients.objects.exclude(deleted=True),
                fields=['document_type', 'number_doc'],
                message="Este número de documento/ruc ya ha sido registrado"
            )
        ]

    def get_level_info(self, obj):
        """Información del nivel actual del cliente - versión simplificada"""
        # Obtener logros obtenidos ordenados por nivel más alto
        earned_achievements = ClientAchievement.objects.filter(
            client=obj,
            deleted=False
        ).select_related('achievement').order_by(
            '-achievement__required_reservations',
            '-achievement__required_referrals',
            '-achievement__required_referral_reservations'
        )
        
        # Obtener el nivel más alto obtenido
        if earned_achievements.exists():
            highest_achievement = earned_achievements.first()
            return {
                'name': highest_achievement.achievement.name,
                'description': highest_achievement.achievement.description,
                'icon': highest_achievement.achievement.icon,
                'earned_at': highest_achievement.earned_at
            }
        
        return None

    def validate(self, attrs):

        document_type = attrs.get('document_type', 'dni')

        # Prevenir crear clientes con nombre mantenimiento
        if attrs.get('first_name') == "Mantenimiento":
            raise serializers.ValidationError('No se puede usar nombre "Mantenimiento" para clientes, esta reservado para uso interno')

        # Prevenir crear clientes con nombre AirBnB
        if attrs.get('first_name') == "AirBnB":
            raise serializers.ValidationError('No se puede usar nombre "AirBnB" para clientes, esta reservado para uso interno')

        # Check if is a person or a company
        if document_type == 'dni' and not attrs.get('last_name'):
            raise serializers.ValidationError("Apellido es obligatorio en personas")


        return attrs


class ClientShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clients
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "tel_number",
            "document_type",
            "number_doc"
        ]


class ClientAuthVerifySerializer(serializers.Serializer):
    document_type = serializers.CharField(max_length=3)
    number_doc = serializers.CharField(max_length=50)


class ClientAuthRequestOTPSerializer(serializers.Serializer):
    document_type = serializers.CharField(max_length=3)
    number_doc = serializers.CharField(max_length=50)


class ClientAuthSetPasswordSerializer(serializers.Serializer):
    document_type = serializers.CharField(max_length=3)
    number_doc = serializers.CharField(max_length=50)
    otp_code = serializers.CharField(max_length=6)
    password = serializers.CharField(min_length=6, max_length=128)


class ClientAuthLoginSerializer(serializers.Serializer):
    document_type = serializers.CharField(max_length=3)
    number_doc = serializers.CharField(max_length=50)
    password = serializers.CharField(max_length=128)


class ClientProfileSerializer(serializers.ModelSerializer):
    available_points = serializers.SerializerMethodField()
    points_are_expired = serializers.SerializerMethodField()
    referred_by_info = serializers.SerializerMethodField()
    referral_code = serializers.SerializerMethodField()
    level_info = serializers.SerializerMethodField()
    achievements_stats = serializers.SerializerMethodField()
    facebook_profile_picture = serializers.SerializerMethodField()
    facebook_name = serializers.SerializerMethodField()

    class Meta:
        model = Clients
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "tel_number",
            "document_type",
            "number_doc",
            "date",
            "sex",
            "last_login",
            "points_balance",
            "points_expires_at",
            "available_points",
            "points_are_expired",
            "referred_by_info",
            "referral_code",
            "level_info",
            "achievements_stats",
            "facebook_linked",
            "facebook_profile_picture",
            "facebook_name",
            "facebook_linked_at"
        ]
        read_only_fields = [
            "id", "document_type", "number_doc", "last_login",
            "points_balance", "points_expires_at", "available_points", "points_are_expired"
        ]

    def get_available_points(self, obj):
        return obj.get_available_points()

    def get_points_are_expired(self, obj):
        return obj.points_are_expired

    def get_referred_by_info(self, obj):
        """Información del cliente que refirió a este cliente"""
        if obj.referred_by:
            return {
                'id': obj.referred_by.id,
                'name': f"{obj.referred_by.first_name} {obj.referred_by.last_name or ''}".strip(),
                'referral_code': obj.referred_by.get_referral_code()
            }
        return None

    def get_referral_code(self, obj):
        """Código de referido del cliente"""
        return obj.get_referral_code()

    def get_level_info(self, obj):
        """Información del nivel actual del cliente"""
        from apps.reservation.models import Reservation
        from django.db.models import Q, Count
        
        # Calcular estadísticas actuales del cliente
        client_reservations = Reservation.objects.filter(
            client=obj,
            deleted=False,
            status='approved'
        ).count()
        
        client_referrals = Clients.objects.filter(
            referred_by=obj,
            deleted=False
        ).count()
        
        referral_reservations = Reservation.objects.filter(
            client__referred_by=obj,
            deleted=False,
            status='approved'
        ).count()
        
        # Obtener logros obtenidos
        earned_achievements = ClientAchievement.objects.filter(
            client=obj,
            deleted=False
        ).select_related('achievement').order_by('-earned_at')
        
        # Obtener el nivel más alto obtenido (no solo el más reciente)
        current_level = None
        if earned_achievements.exists():
            # Ordenar por requisitos para obtener el nivel más alto
            highest_achievement = earned_achievements.select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            ).first()
            
            current_level = {
                'name': highest_achievement.achievement.name,
                'description': highest_achievement.achievement.description,
                'icon': highest_achievement.achievement.icon,
                'earned_at': highest_achievement.earned_at
            }
        
        # Buscar el siguiente logro disponible
        earned_achievement_ids = earned_achievements.values_list('achievement_id', flat=True)
        next_achievement = Achievement.objects.filter(
            is_active=True,
            deleted=False
        ).exclude(id__in=earned_achievement_ids).order_by('order', 'required_reservations', 'required_referrals').first()
        
        next_level = None
        progress = None
        if next_achievement:
            next_level = {
                'name': next_achievement.name,
                'description': next_achievement.description,
                'icon': next_achievement.icon,
                'required_reservations': next_achievement.required_reservations,
                'required_referrals': next_achievement.required_referrals,
                'required_referral_reservations': next_achievement.required_referral_reservations
            }
            
            # Calcular progreso hacia el siguiente nivel
            progress = {
                'reservations': {
                    'current': client_reservations,
                    'required': next_achievement.required_reservations,
                    'remaining': max(0, next_achievement.required_reservations - client_reservations)
                },
                'referrals': {
                    'current': client_referrals,
                    'required': next_achievement.required_referrals,
                    'remaining': max(0, next_achievement.required_referrals - client_referrals)
                },
                'referral_reservations': {
                    'current': referral_reservations,
                    'required': next_achievement.required_referral_reservations,
                    'remaining': max(0, next_achievement.required_referral_reservations - referral_reservations)
                }
            }
        
        return {
            'current_level': current_level,
            'next_level': next_level,
            'progress': progress,
            'total_achievements': earned_achievements.count()
        }

    def get_achievements_stats(self, obj):
        """Estadísticas de logros del cliente"""
        from apps.reservation.models import Reservation
        from django.db.models import Q, Count
        
        # Calcular estadísticas actuales
        client_reservations = Reservation.objects.filter(
            client=obj,
            deleted=False,
            status='approved'
        ).count()
        
        client_referrals = Clients.objects.filter(
            referred_by=obj,
            deleted=False
        ).count()
        
        referral_reservations = Reservation.objects.filter(
            client__referred_by=obj,
            deleted=False,
            status='approved'
        ).count()
        
        # Contar logros totales
        total_achievements = Achievement.objects.filter(
            is_active=True,
            deleted=False
        ).count()
        
        earned_achievements = ClientAchievement.objects.filter(
            client=obj,
            deleted=False
        ).count()
        
        return {
            'client_stats': {
                'reservations': client_reservations,
                'referrals': client_referrals,
                'referral_reservations': referral_reservations
            },
            'achievements': {
                'earned': earned_achievements,
                'total': total_achievements,
                'percentage': round((earned_achievements / total_achievements * 100), 1) if total_achievements > 0 else 0
            }
        }
    
    def get_facebook_profile_picture(self, obj):
        """URL de la foto de perfil de Facebook"""
        return obj.get_facebook_profile_picture()
    
    def get_facebook_name(self, obj):
        """Nombre del perfil de Facebook"""
        if obj.facebook_profile_data and isinstance(obj.facebook_profile_data, dict):
            return obj.facebook_profile_data.get('name')
        return None




class ClientPointsSerializer(serializers.ModelSerializer):
    """Serializer para transacciones de puntos"""
    reservation_id = serializers.IntegerField(source='reservation.id', read_only=True)

    class Meta:
        model = ClientPoints
        fields = [
            'id', 'transaction_type', 'points', 'description', 
            'expires_at', 'created', 'reservation_id'
        ]
        read_only_fields = ['id', 'created']


class ClientPointsBalanceSerializer(serializers.ModelSerializer):
    """Serializer para balance de puntos del cliente"""
    available_points = serializers.SerializerMethodField()
    points_are_expired = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()

    class Meta:
        model = Clients
        fields = [
            'points_balance', 'points_expires_at', 'available_points', 
            'points_are_expired', 'recent_transactions'
        ]

    def get_available_points(self, obj):
        return obj.get_available_points()

    def get_points_are_expired(self, obj):
        return obj.points_are_expired

    def get_recent_transactions(self, obj):
        recent_transactions = ClientPoints.objects.filter(
            client=obj, deleted=False
        ).order_by('-created')[:5]
        return ClientPointsSerializer(recent_transactions, many=True).data


class RedeemPointsSerializer(serializers.Serializer):
    """Serializer para canjear puntos"""
    points_to_redeem = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))

    def validate_points_to_redeem(self, value):
        client = self.context.get('client')
        if not client:
            raise serializers.ValidationError("Cliente no encontrado")

        available_points = client.get_available_points()
        if value > available_points:
            raise serializers.ValidationError(
                f"No tienes suficientes puntos. Disponibles: {available_points}"
            )

        return value


class SearchTrackingSerializer(serializers.ModelSerializer):
    """Serializer para tracking de búsquedas - Versión simplificada para debug"""
    property_name = serializers.CharField(source='property.name', read_only=True)

    class Meta:
        model = SearchTracking
        fields = [
            'check_in_date', 'check_out_date', 'guests', 'property', 
            'property_name', 'search_timestamp'
        ]
        read_only_fields = ['search_timestamp']

    def validate(self, attrs):
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"SearchTrackingSerializer.validate: ENTRADA - attrs recibidos: {attrs}")
        logger.info(f"SearchTrackingSerializer.validate: ENTRADA - tipo de attrs: {type(attrs)}")

        # Log cada campo individual
        for key, value in attrs.items():
            logger.info(f"SearchTrackingSerializer.validate: CAMPO '{key}' = '{value}' (tipo: {type(value)})")

        # NO hacer validaciones complejas por ahora, solo log y retornar
        logger.info(f"SearchTrackingSerializer.validate: SALIDA - retornando attrs: {attrs}")
        return attrs


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            'id',
            'name', 
            'description',
            'icon',
            'required_reservations',
            'required_referrals', 
            'required_referral_reservations',
            'order'
        ]


class ClientAchievementSerializer(serializers.ModelSerializer):
    achievement = AchievementSerializer(read_only=True)

    class Meta:
        model = ClientAchievement
        fields = [
            'id',
            'achievement',
            'earned_at'
        ]


class ClientAchievementStatsSerializer(serializers.Serializer):
    """Serializer para estadísticas de logros del cliente"""
    total_achievements = serializers.IntegerField()
    recent_achievements = ClientAchievementSerializer(many=True)
    available_achievements = AchievementSerializer(many=True)
    client_stats = serializers.DictField()