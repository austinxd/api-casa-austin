from rest_framework import serializers

from .models import Clients


class ClientsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clients
        exclude = ["created", "updated", "deleted"]

class ClientShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clients
        fields = ["id", "first_name", "last_name"]