from rest_framework import serializers

from apps.property.models import Property
from apps.property.serializers import PropertySerializer


class DashboardSerializer(serializers.Serializer):
    num_reservas = serializers.IntegerField()
    property = serializers.SerializerMethodField()
    percentage = serializers.FloatField()
    background_color = serializers.CharField()
    
    def get_property(self, instance):
        return PropertySerializer(Property.objects.filter(id=instance["property"]).first()).data
