from rest_framework import serializers
from apps.property.models import Property
from apps.clients.models import Clients
from apps.reservation.models import Reservation


class TVGuestSerializer(serializers.ModelSerializer):
    """Serializer for guest information displayed on TV."""

    class Meta:
        model = Clients
        fields = ['first_name', 'last_name', 'email']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Add language preference (default to Spanish if not set)
        data['language'] = getattr(instance, 'preferred_language', 'es') or 'es'
        return data


class TVPropertySerializer(serializers.ModelSerializer):
    """Serializer for property information displayed on TV."""

    class Meta:
        model = Property
        fields = ['id', 'name', 'location']


class TVSessionResponseSerializer(serializers.Serializer):
    """Response serializer for TV session endpoint."""

    active = serializers.BooleanField()
    guest = TVGuestSerializer(required=False, allow_null=True)
    check_in_date = serializers.DateField(required=False, allow_null=True)
    check_out_date = serializers.DateField(required=False, allow_null=True)
    property = TVPropertySerializer(required=False, allow_null=True)
    message = serializers.CharField(required=False, allow_null=True)


class TVHeartbeatSerializer(serializers.Serializer):
    """Serializer for heartbeat requests."""

    timestamp = serializers.DateTimeField(required=False)
    app_in_use = serializers.CharField(required=False, allow_null=True)


class TVCheckoutSerializer(serializers.Serializer):
    """Serializer for checkout requests."""

    reason = serializers.CharField(required=False, allow_null=True)
