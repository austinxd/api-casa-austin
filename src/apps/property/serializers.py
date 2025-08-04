from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Property, ProfitPropertyAirBnb


class PropertyListSerializer(serializers.ModelSerializer):
    """Serializer ligero para listados - solo información básica"""
    class Meta:
        model = Property
        fields = [
            "id", 
            "name",
            "slug", 
            "location", 
            "capacity_max", 
            "dormitorios", 
            "banos", 
            "hora_ingreso", 
            "hora_salida", 
            "caracteristicas",
            "background_color",
            "precio_desde"
        ]


class PropertyDetailSerializer(serializers.ModelSerializer):
    """Serializer completo para vista de detalle"""
    class Meta:
        model = Property
        exclude = ["created", "updated", "deleted"]
        
    def validate_detalle_dormitorios(self, value):
        """Validar que el detalle de dormitorios sea un diccionario válido"""
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("El detalle de dormitorios debe ser un objeto JSON válido")
        return value
    
    def validate_caracteristicas(self, value):
        """Validar que las características sean una lista válida"""
        if value and not isinstance(value, list):
            raise serializers.ValidationError("Las características deben ser una lista válida")
        return value


# Mantener compatibilidad hacia atrás
PropertySerializer = PropertyDetailSerializer

class ProfitPropertyAirBnbSerializer(serializers.ModelSerializer):
    property = serializers.SerializerMethodField()
    class Meta:
        model = ProfitPropertyAirBnb
        exclude = ["created", "updated", "deleted"]

    @extend_schema_field(PropertySerializer)
    def get_property(self, instance):
        return PropertySerializer(instance.property).data