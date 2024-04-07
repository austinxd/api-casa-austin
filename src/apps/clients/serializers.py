from rest_framework import serializers

from .models import Clients, TokenApiClients


class TokenApiClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenApiClients
        exclude = ["id", "created", "updated", "deleted"]

class ClientsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clients
        exclude = ["created", "updated", "deleted"]

class ClientShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clients
        fields = ["id", "first_name", "last_name", "email", "tel_number"]