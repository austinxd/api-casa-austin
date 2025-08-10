from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.validators import UniqueTogetherValidator
from decimal import Decimal

from .models import Clients, MensajeFidelidad, TokenApiClients, ClientPoints, SearchTracking


class MensajeFidelidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MensajeFidelidad
        fields = ["mensaje"]

class TokenApiClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenApiClients
        exclude = ["id", "created", "updated", "deleted"]

class ClientsSerializer(serializers.ModelSerializer):
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
            "referral_code"
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
    """Serializer para tracking de búsquedas"""
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
        
        logger.info(f"SearchTrackingSerializer.validate: Received attrs: {attrs}")
        
        check_in = attrs.get('check_in_date')
        check_out = attrs.get('check_out_date')
        
        logger.info(f"SearchTrackingSerializer.validate: check_in = {check_in} (type: {type(check_in)})")
        logger.info(f"SearchTrackingSerializer.validate: check_out = {check_out} (type: {type(check_out)})")
        
        # Validar que las fechas requeridas estén presentes
        if not check_in:
            logger.error("SearchTrackingSerializer.validate: check_in_date is missing or empty")
            raise serializers.ValidationError({
                "check_in_date": "La fecha de check-in es requerida"
            })
        
        if not check_out:
            logger.error("SearchTrackingSerializer.validate: check_out_date is missing or empty")
            raise serializers.ValidationError({
                "check_out_date": "La fecha de check-out es requerida"
            })
        
        if check_in >= check_out:
            logger.error(f"SearchTrackingSerializer.validate: Invalid date range: {check_in} >= {check_out}")
            raise serializers.ValidationError(
                "La fecha de check-out debe ser posterior a la fecha de check-in"
            )
        
        guests = attrs.get('guests')
        logger.info(f"SearchTrackingSerializer.validate: guests = {guests} (type: {type(guests)})")
        
        if not guests or guests <= 0:
            logger.error(f"SearchTrackingSerializer.validate: Invalid guests value: {guests}")
            raise serializers.ValidationError({
                "guests": "El número de huéspedes debe ser mayor a 0"
            })
        
        logger.info("SearchTrackingSerializer.validate: All validations passed")
        return attrs