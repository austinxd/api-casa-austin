from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Property, ProfitPropertyAirBnb


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        exclude = ["created", "updated", "deleted"]

class ProfitPropertyAirBnbSerializer(serializers.ModelSerializer):
    property = serializers.SerializerMethodField()
    class Meta:
        model = ProfitPropertyAirBnb
        exclude = ["created", "updated", "deleted"]

    @extend_schema_field(PropertySerializer)
    def get_property(self, instance):
        return PropertySerializer(instance.property).data