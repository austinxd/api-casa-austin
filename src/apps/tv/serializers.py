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
    image_url = serializers.SerializerMethodField()
    welcome_message = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ['id', 'name', 'location', 'image_url', 'welcome_message']

    def get_image_url(self, obj):
        """Get the main photo URL for the property (absolute URL)."""
        from apps.property.models import PropertyPhoto

        main_photo = PropertyPhoto.objects.filter(
            property=obj,
            is_main=True,
            deleted=False
        ).first()

        photo = main_photo
        if not photo:
            # Fallback to first photo if no main photo
            photo = PropertyPhoto.objects.filter(
                property=obj,
                deleted=False
            ).order_by('order').first()

        if not photo:
            return None

        image_url = photo.get_image_url()
        if not image_url:
            return None

        # If it's already an absolute URL, return as is
        if image_url.startswith('http'):
            return image_url

        # Build absolute URL from relative path
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(image_url)

        # Fallback: prepend base URL
        return f"https://api.casaaustin.pe{image_url}"

    def get_welcome_message(self, obj):
        """Get welcome message for the property."""
        if obj.descripcion:
            return obj.descripcion[:200]  # Limit length
        return f"Bienvenido a {obj.name}"


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
