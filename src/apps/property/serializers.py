from rest_framework import serializers

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

    def get_property(self, instance):
        return PropertySerializer(instance.property).data