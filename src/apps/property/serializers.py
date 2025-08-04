from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto


class PropertyPhotoSerializer(serializers.ModelSerializer):
    """Serializer para las fotos de propiedades"""
    class Meta:
        model = PropertyPhoto
        fields = ["id", "image_url", "alt_text", "order", "is_main"]



class PropertyListSerializer(serializers.ModelSerializer):
    """Serializer ligero para listados - solo información básica"""
    photos = PropertyPhotoSerializer(many=True, read_only=True)
    main_photo = serializers.SerializerMethodField()

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
            "precio_desde",
            "photos",
            "main_photo"
        ]

    def get_main_photo(self, obj):
        """Obtener la foto principal o la primera foto disponible"""
        main_photo = obj.photos.filter(is_main=True, deleted=False).first()
        if not main_photo:


    def get_main_photo(self, obj):
        """Obtener la foto principal o la primera foto disponible"""
        main_photo = obj.photos.filter(is_main=True, deleted=False).first()
        if not main_photo:
            main_photo = obj.photos.filter(deleted=False).first()

        if main_photo:
            return PropertyPhotoSerializer(main_photo).data
        return None

            main_photo = obj.photos.filter(deleted=False).first()

        if main_photo:
            return PropertyPhotoSerializer(main_photo).data
        return None


class PropertyDetailSerializer(serializers.ModelSerializer):
    """Serializer completo para vista de detalle"""
    photos = PropertyPhotoSerializer(many=True, read_only=True)
    main_photo = serializers.SerializerMethodField()

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