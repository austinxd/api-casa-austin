from rest_framework import serializers

from .models import Property, ProfitPropertyAirBnb


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        exclude = ["created", "updated", "deleted"]

class ProfitPropertyAirBnbSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfitPropertyAirBnb
        exclude = ["created", "updated", "deleted"]
