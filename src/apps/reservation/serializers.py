from django.db.models import Q
from rest_framework import serializers
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field

from .models import Reservation, RentalReceipt
from apps.clients.models import Clients
from apps.accounts.models import CustomUser

from apps.accounts.serializers import SellerSerializer
from apps.clients.serializers import ClientShortSerializer
from apps.property.serializers import PropertySerializer

from apps.core.functions import check_user_has_rol


class ReciptSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    class Meta:
        model = RentalReceipt
        fields = ["id", "file"]

    @extend_schema_field(serializers.FileField)
    def get_file(self, instance):
        request = self.context.get('request', None)
        if request and instance.file:
            return request.build_absolute_uri(instance.file.url)
        return None


class ReservationSerializer(serializers.ModelSerializer):
    points_to_redeem = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        required=False, 
        write_only=True,
        min_value=Decimal('0'),
        help_text="Puntos a canjear en esta reserva"
    )
    
    class Meta:
        model = Reservation
        exclude = ["created", "updated", "deleted"]


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance:
            self.fields['seller'].required = False
            self.fields['seller'].read_only = True

    def to_internal_value(self, data):
        new_data = data.copy()

        query_client = Clients.objects.filter(id=data.get('client'))

        if query_client.exists():
            if query_client.first().first_name == 'Mantenimiento':
                self.context['mantenimiento_client'] = query_client.first().first_name
                new_data['origin'] = 'man'
                new_data['price_usd'] = 0
                new_data['price_sol'] = 0
                new_data['advance_payment'] = 0
                new_data['full_payment'] = False
                new_data['temperature_pool'] = False

            elif query_client.first().first_name == 'AirBnB':
                new_data['origin'] = 'air'
                new_data['seller'] = CustomUser.objects.get(first_name='AirBnB').id

        return super().to_internal_value(new_data)

    def validate(self, attrs):
        request = self.context.get('request')

        # Prevenir que usuarios sin rol Admin puedan crear eventos de mantenimiento
        if self.context.get('mantenimiento_client') == 'Mantenimiento':
            if not check_user_has_rol("admin", self.context['request'].user):
                raise serializers.ValidationError("No puede registrar Eventos de Mantenimiento un usuario con rol distinto a Admin.")

        property_field = attrs.get('property')
        reservation_id = self.instance.id if self.instance else None

        # Validar canje de puntos si se especifica
        points_to_redeem = attrs.get('points_to_redeem')
        if points_to_redeem and points_to_redeem > 0:
            client = attrs.get('client')
            if not client:
                raise serializers.ValidationError("Debe especificar un cliente para canjear puntos")
            
            # Verificar que el cliente tenga suficientes puntos
            available_points = client.get_available_points()
            if points_to_redeem > available_points:
                raise serializers.ValidationError(
                    f"El cliente no tiene suficientes puntos. Disponibles: {available_points}, solicitados: {points_to_redeem}"
                )

        if attrs.get('full_payment') == True:
            # Obtener puntos ya canjeados (si estamos actualizando una reserva existente)
            points_redeemed = 0
            if self.instance:
                points_redeemed = float(self.instance.points_redeemed or 0)
            
            if attrs['advance_payment_currency'] == 'sol':
                # Precio total menos puntos ya canjeados
                attrs['advance_payment'] = float(attrs.get('price_sol', 0)) - points_redeemed
            else:
                # Para USD, convertir puntos a dólares usando la tasa de cambio
                price_sol = float(attrs.get('price_sol', 0))
                price_usd = float(attrs.get('price_usd', 0))
                
                if price_usd > 0 and price_sol > 0:
                    # Calcular tasa de cambio: soles por dólar
                    exchange_rate = price_sol / price_usd
                    # Convertir puntos (en soles) a dólares
                    points_in_usd = points_redeemed / exchange_rate
                    attrs['advance_payment'] = price_usd - points_in_usd
                else:
                    attrs['advance_payment'] = attrs.get('price_usd', 0)

        # Check if it's called from a view with patch verb
        patch_cond = False
        if request:
            if request.method != 'PATCH':
                patch_cond = True

        if patch_cond and attrs.get('check_in_date') and attrs.get('check_out_date'):
            # Check if checkin is after checkout
            if attrs.get('check_in_date') >= attrs.get('check_out_date'):
                raise serializers.ValidationError("Fecha entrada debe ser anterior a fecha de salida")

            # Check if this property si reserved in this range of date
            if Reservation.objects.exclude(deleted=True
                ).filter(
                    property=property_field
                ).filter(
                    Q(check_in_date__lt=attrs.get('check_out_date')) & Q(check_out_date__gt=attrs.get('check_in_date'))
                ).exclude(
                    id=reservation_id
                ).exists():

                raise serializers.ValidationError("Esta propiedad esta reservada en este rango de fecha")
        
        return attrs

    def create(self, validated_data):
        # Extraer puntos a canjear antes de crear la reserva
        points_to_redeem = validated_data.pop('points_to_redeem', 0)
        
        # Crear la reserva
        reservation = super().create(validated_data)
        
        # Si hay puntos para canjear, procesarlos
        if points_to_redeem and points_to_redeem > 0:
            # Guardar los puntos canjeados en la reserva
            reservation.points_redeemed = points_to_redeem
            reservation.save()
            
            # Descontar los puntos del cliente
            reservation.client.redeem_points(
                points=points_to_redeem,
                reservation=reservation,
                description=f"Puntos canjeados en reserva #{reservation.id} - {reservation.property.name}"
            )
        
        return reservation

    def update(self, instance, validated_data):
        # Los puntos ya canjeados no se pueden modificar en updates
        validated_data.pop('points_to_redeem', None)
        return super().update(instance, validated_data)

class ReservationListSerializer(ReservationSerializer):
    client = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    property = serializers.SerializerMethodField()
    resta_pagar = serializers.SerializerMethodField()
    number_nights = serializers.SerializerMethodField()
    is_upcoming = serializers.SerializerMethodField()
    
    @extend_schema_field(ClientShortSerializer)
    def get_client(self, instance):
        return ClientShortSerializer(instance.client).data

    @extend_schema_field(SellerSerializer)
    def get_seller(self, instance):
        return SellerSerializer(instance.seller).data

    @extend_schema_field(PropertySerializer)
    def get_property(self, instance):
        return PropertySerializer(instance.property).data
    
    @extend_schema_field(serializers.FloatField())
    def get_resta_pagar(self, instance):
        return '%.2f' % round(float(instance.price_sol) - instance.adelanto_normalizado, 2)
    
    @extend_schema_field(serializers.IntegerField())
    def get_number_nights(self, instance):
        if instance.check_in_date and instance.check_out_date:
            delta = instance.check_out_date - instance.check_in_date
            return delta.days
        return 0
    
    @extend_schema_field(serializers.BooleanField())
    def get_is_upcoming(self, instance):
        from datetime import date
        today = date.today()
        return instance.check_out_date > today

class ReservationRetrieveSerializer(ReservationListSerializer):
    recipts = serializers.SerializerMethodField()

    @extend_schema_field(ReciptSerializer)
    def get_recipts(self, instance):
        return ReciptSerializer(
            RentalReceipt.objects.filter(reservation=instance), 
            context={'request': self.context.get('request', None)},  
            many=True
        ).data
