from rest_framework import serializers
from .models import CustomUser

class SellerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "first_name", "last_name"]