from django.db.models import Q
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Reservation, RentalReceipt
from apps.clients.models import Clients
from apps.accounts.models import CustomUser

from apps.accounts.serializers import SellerSerializer
from apps.clients.serializers import ClientShortSerializer
from apps.property.serializers import PropertySerializer

from apps.core.functions import check_user_has_rol
from datetime import timedelta


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
        self.fields["comentarios_reservas"] = serializers.CharField(required=False, allow_blank=True, allow_null=True)

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
    # Obtener el objeto 'request' desde el contexto del serializer
    request = self.context.get('request')

    # Prevenir la creación de eventos de mantenimiento por usuarios que no sean administradores
    if self.context.get('mantenimiento_client') == 'Mantenimiento':
        if not check_user_has_rol("admin", request.user):
            raise serializers.ValidationError("No puede registrar Eventos de Mantenimiento un usuario con rol distinto a Admin.")

    # Extraer los campos de 'property' y 'reservation_id' desde 'attrs' y 'instance'
    property_field = attrs.get('property')
    reservation_id = self.instance.id if self.instance else None

    # Lógica para asignar el pago adelantado basado en la moneda especificada
    if attrs.get('full_payment') == True:
        if attrs['advance_payment_currency'] == 'sol':
            attrs['advance_payment'] = attrs.get('price_sol')
        else:
            attrs['advance_payment'] = attrs.get('price_usd')

    # Verificar si la solicitud actual es una actualización (PATCH) y si existe una instancia de reserva
    if request and request.method == 'PATCH' and self.instance:
        # Si 'late_checkout' ha sido enviado y es diferente al valor existente en la base de datos
        if 'late_checkout' in attrs and attrs['late_checkout'] != self.instance.late_checkout:
            # Y si 'late_checkout' es verdadero y se proporciona una fecha de salida
            if attrs.get('late_checkout') and attrs.get('check_out_date'):
                # Entonces ajustar la fecha de salida agregando un día
                attrs['late_check_out_date'] = attrs['check_out_date']
                attrs['check_out_date'] += timedelta(days=1)

    # Si la solicitud no es PATCH o no existe una instancia
    else:
        # Verificar que la fecha de entrada no sea posterior a la fecha de salida
        if attrs.get('check_in_date') and attrs.get('check_out_date'):
            if attrs['check_in_date'] >= attrs['check_out_date']:
                raise serializers.ValidationError("Fecha de entrada debe ser anterior a fecha de salida")

        # Verificar si la propiedad está reservada en el rango de fechas dado, excluyendo la reserva actual si existe
        if Reservation.objects.exclude(deleted=True).filter(
            property=property_field,
            check_in_date__lt=attrs.get('check_out_date'),
            check_out_date__gt=attrs.get('check_in_date')
        ).exclude(id=reservation_id).exists():
            raise serializers.ValidationError("Esta propiedad está reservada en este rango de fecha")

    # Devolver los atributos validados
    return attrs

class ReservationListSerializer(ReservationSerializer):
    client = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    property = serializers.SerializerMethodField()
    resta_pagar = serializers.SerializerMethodField()
    
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

class ReservationRetrieveSerializer(ReservationListSerializer):
    recipts = serializers.SerializerMethodField()

    @extend_schema_field(ReciptSerializer)
    def get_recipts(self, instance):
        return ReciptSerializer(
            RentalReceipt.objects.filter(reservation=instance), 
            context={'request': self.context.get('request', None)},  
            many=True
        ).data
