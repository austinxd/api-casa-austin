
from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.validators import UniqueTogetherValidator

from .models import Clients, MensajeFidelidad, TokenApiClients


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
            "last_login"
        ]
        read_only_fields = ["id", "document_type", "number_doc", "last_login"]



from .models import ClientPoints

class ClientPointsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientPoints
        fields = ['id', 'transaction_type', 'points', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']


class ClientPointsSummarySerializer(serializers.ModelSerializer):
    total_points = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()
    
    class Meta:
        model = Clients
        fields = ['total_points', 'recent_transactions']
    
    def get_total_points(self, obj):
        return obj.total_points()
    
    def get_recent_transactions(self, obj):
        recent = obj.point_transactions.all()[:5]
        return ClientPointsSerializer(recent, many=True).data


class RedeemPointsSerializer(serializers.Serializer):
    points_to_redeem = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    
    def validate_points_to_redeem(self, value):
        client = self.context['client']
        available_points = client.total_points()
        
        if value > available_points:
            raise serializers.ValidationError(f"No tienes suficientes puntos. Disponibles: {available_points}")
        
        return value
