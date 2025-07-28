
from rest_framework import serializers

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
