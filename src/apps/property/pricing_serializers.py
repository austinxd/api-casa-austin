
from rest_framework import serializers
from decimal import Decimal
from .pricing_models import ExchangeRate, AdditionalService, CancellationPolicy


class AdditionalServiceSerializer(serializers.ModelSerializer):
    price_sol = serializers.SerializerMethodField()
    total_price_usd = serializers.SerializerMethodField()
    total_price_sol = serializers.SerializerMethodField()
    
    class Meta:
        model = AdditionalService
        fields = [
            'id', 'name', 'description', 'price_usd', 'price_sol',
            'service_type', 'is_per_night', 'is_per_person',
            'total_price_usd', 'total_price_sol'
        ]
    
    def get_price_sol(self, obj):
        exchange_rate = ExchangeRate.get_current_rate()
        return float(obj.price_usd * exchange_rate)
    
    def get_total_price_usd(self, obj):
        context = self.context
        nights = context.get('nights', 1)
        guests = context.get('guests', 1)
        return float(obj.calculate_price(nights, guests))
    
    def get_total_price_sol(self, obj):
        context = self.context
        nights = context.get('nights', 1)
        guests = context.get('guests', 1)
        exchange_rate = ExchangeRate.get_current_rate()
        total_usd = obj.calculate_price(nights, guests)
        return float(total_usd * exchange_rate)


class CancellationPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = CancellationPolicy
        fields = ['id', 'name', 'description', 'days_before_checkin', 'refund_percentage']


class PropertyPricingSerializer(serializers.Serializer):
    property_id = serializers.IntegerField()
    property_name = serializers.CharField()
    property_slug = serializers.CharField()
    base_price_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    base_price_sol = serializers.DecimalField(max_digits=10, decimal_places=2)
    extra_person_price_per_night_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    extra_person_price_per_night_sol = serializers.DecimalField(max_digits=10, decimal_places=2)
    extra_person_total_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    extra_person_total_sol = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_nights = serializers.IntegerField()
    total_guests = serializers.IntegerField()
    extra_guests = serializers.IntegerField()
    subtotal_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    subtotal_sol = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount_applied = serializers.DictField(required=False)
    final_price_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    final_price_sol = serializers.DecimalField(max_digits=10, decimal_places=2)
    available = serializers.BooleanField()
    availability_message = serializers.CharField()
    additional_services = AdditionalServiceSerializer(many=True)
    cancellation_policy = CancellationPolicySerializer()
    client_benefits = serializers.DictField(required=False)
    recommendations = serializers.ListField()


class PricingCalculationSerializer(serializers.Serializer):
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    guests = serializers.IntegerField(min_value=1)
    total_nights = serializers.IntegerField()
    exchange_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    properties = PropertyPricingSerializer(many=True)
    general_recommendations = serializers.ListField()
    client_info = serializers.DictField(required=False)
    
    def validate(self, data):
        if data['check_in_date'] >= data['check_out_date']:
            raise serializers.ValidationError("La fecha de salida debe ser posterior a la fecha de entrada")
        return data
