from django.db.models import Q
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Reservation, RentalReceipt
from apps.clients.models import Clients

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
    class Meta:
        model = Reservation
        exclude = ["created", "updated", "deleted"]


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance:
            self.fields['seller'].required = False
            self.fields['seller'].read_only = True
            script = self.context.get("script", None) # es para determinar si la creacion de reserva viene del script
            if script:
                self.fields['seller'].read_only = False # FIXME: cambiar a true luego de definir las reservas de airbnb

    def to_internal_value(self, data):
        new_data = data.copy()
        query_client = Clients.objects.filter(id=data['client'])

        if query_client.exists():
            if query_client.first().first_name == 'Mantenimiento':
                self.context['mantenimiento_client'] = query_client.first().first_name
                new_data['origin'] = 'man'

        return super().to_internal_value(new_data)

    def validate(self, attrs):
        request = self.context.get('request')

        # Prevenir que usuarios sin rol Admin puedan crear eventos de mantenimiento
        if self.context.get('mantenimiento_client') == 'Mantenimiento':
            if not check_user_has_rol("admin", self.context['request'].user):
                raise serializers.ValidationError("No puede registrar Eventos de Mantenimiento un usuario con rol distinto a Admin.")

        property_field = attrs.get('property')
        reservation_id = self.instance.id if self.instance else None
        
        print("\n\n")
        print('self comtext!!! ', attrs)
        print("\n\n")
        
        print("\n\n")
        print('self ATTRSSSS!!! ', attrs['advance_payment'])
        print("\n\n")
        if attrs.get('advance_payment_currency') == 'usd' and attrs.get('advance_payment') > 0:
            print("\n\n")
            print('ENTRO PRIMER IFF CURRENCY USD!!!' )
            print("\n\n")
            # Calculo cotizacion 1 dolar = soles
            usd_x_sol = attrs.get('price_sol')/attrs.get('price_usd')
            attrs['advance_payment'] = attrs.get('advance_payment')*usd_x_sol

        if attrs.get('full_payment') == True:
            attrs['advance_payment'] = attrs.get('price_sol')
            attrs['advance_payment_currency'] == 'sol'


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

class ReservationListSerializer(ReservationSerializer):
    client = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    property = serializers.SerializerMethodField()
    
    @extend_schema_field(ClientShortSerializer)
    def get_client(self, instance):
        return ClientShortSerializer(instance.client).data

    @extend_schema_field(SellerSerializer)
    def get_seller(self, instance):
        return SellerSerializer(instance.seller).data

    @extend_schema_field(PropertySerializer)
    def get_property(self, instance):
        return PropertySerializer(instance.property).data

class ReservationRetrieveSerializer(ReservationListSerializer):
    recipts = serializers.SerializerMethodField()

    @extend_schema_field(ReciptSerializer)
    def get_recipts(self, instance):
        return ReciptSerializer(
            RentalReceipt.objects.filter(reservation=instance), 
            context={'request': self.context.get('request', None)},  
            many=True
        ).data