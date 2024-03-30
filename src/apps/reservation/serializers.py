from django.db.models import Q
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from .models import Reservation, RentalReceipt

from apps.accounts.serializers import SellerSerializer
from apps.clients.serializers import ClientShortSerializer
from apps.property.serializers import PropertySerializer


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
            self.fields['seller'].read_only = False # FIXME: cambiar a true luego de definir las reservas de airbnb

    def validate(self, attrs):

        property_field = attrs.get('property')
        reservation_id = self.instance.id if self.instance else None

        # Check if checkin is after checkout
        if attrs.get('check_in_date') > attrs.get('check_out_date'):
            raise serializers.ValidationError({'check_in_date':"Check in date must be later than Check out date"})

        # Check if this property si reserved in this range of date
        if Reservation.objects.filter(
                property=property_field,
            ).filter(
                Q(check_in_date__lt=attrs.get('check_out_date')) & Q(check_out_date__gt=attrs.get('check_in_date'))
            ).exclude(
                id=reservation_id
            ).exists():

            raise serializers.ValidationError({'property':"The property is booked on those dates."})

        
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