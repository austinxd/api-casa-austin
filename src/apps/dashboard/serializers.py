from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from apps.property.models import Property
from apps.property.serializers import PropertySerializer


class DashboardSerializer(serializers.Serializer):
    num_reservas = serializers.IntegerField()
    property = serializers.SerializerMethodField()
    percentage = serializers.FloatField()
    background_color = serializers.CharField()
    
    @extend_schema_field(PropertySerializer)
    def get_property(self, instance):
        return PropertySerializer(Property.objects.filter(id=instance["property"]).first()).data
