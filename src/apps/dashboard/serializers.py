from rest_framework import serializers

from apps.property.models import Property
from apps.property.serializers import PropertySerializer


class DashboardSerializer(serializers.Serializer):
    # id = serializers.UUIDField(required=False)
    # property = PropertySerializer()
    num_reservas = serializers.IntegerField()
    property = serializers.SerializerMethodField()
    percentage = serializers.FloatField()
    
    def get_property(self, instance):
        prop = Property.objects.filter(id=instance["property"]).first()
        return PropertySerializer(prop).data
