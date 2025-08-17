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
        # Solo procesar datos si es una operación de escritura (POST, PUT, PATCH)
        request = self.context.get('request')
        if not request or request.method in ['GET', 'HEAD', 'OPTIONS']:
            return super().to_internal_value(data)
            
        # Evitar deepcopy cuando hay archivos presentes para prevenir error de pickle
        if hasattr(data, 'getlist') and any(hasattr(item, 'read') for items in data.values() for item in (items if isinstance(items, list) else [items])):
            # Si hay archivos, crear un QueryDict mutable sin deepcopy
            from django.http import QueryDict
            new_data = QueryDict(mutable=True)
            for key, value in data.items():
                if isinstance(value, list):
                    for v in value:
                        new_data.appendlist(key, v)
                else:
                    new_data[key] = value
        else:
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

        # Si la reserva viene del endpoint de cliente Y no tiene origin 'aus', marcarla como cliente
        if self.context.get('from_client_endpoint') and data.get('origin') != 'aus':
            new_data['origin'] = 'client'
            new_data['status'] = 'pending'

        return super().to_internal_value(new_data)

    def validate(self, attrs):
        request = self.context.get('request')

        # Prevenir que usuarios sin rol Admin puedan crear eventos de mantenimiento
        if self.context.get('mantenimiento_client') == 'Mantenimiento':
            if not check_user_has_rol("admin", self.context['request'].user):
                raise serializers.ValidationError("No puede registrar Eventos de Mantenimiento un usuario con rol distinto a Admin.")

        property_field = attrs.get('property')
        reservation_id = self.instance.id if self.instance else None

        # Validar canje de puntos si se especifica (solo en creación, no en PATCH)
        points_to_redeem = attrs.get('points_to_redeem')
        is_patch = request and request.method == 'PATCH'
        
        if points_to_redeem and points_to_redeem > 0 and not is_patch:
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
            
            # En PATCH, usar los datos existentes si no se proporcionan nuevos valores
            if is_patch and self.instance:
                price_sol = float(attrs.get('price_sol', self.instance.price_sol or 0))
                price_usd = float(attrs.get('price_usd', self.instance.price_usd or 0))
                currency = attrs.get('advance_payment_currency', self.instance.advance_payment_currency or 'sol')
            else:
                price_sol = float(attrs.get('price_sol', 0))
                price_usd = float(attrs.get('price_usd', 0))
                currency = attrs.get('advance_payment_currency', 'sol')
            
            if currency == 'sol':
                # Precio total menos puntos ya canjeados
                attrs['advance_payment'] = price_sol - points_redeemed
            else:
                # Para USD, convertir puntos a dólares usando la tasa de cambio
                if price_usd > 0 and price_sol > 0:
                    # Calcular tasa de cambio: soles por dólar
                    exchange_rate = price_sol / price_usd
                    # Convertir puntos (en soles) a dólares
                    points_in_usd = points_redeemed / exchange_rate
                    attrs['advance_payment'] = price_usd - points_in_usd
                else:
                    attrs['advance_payment'] = price_usd

        # Solo validar fechas y disponibilidad si NO es PATCH
        should_validate_dates = True
        if request and request.method == 'PATCH':
            should_validate_dates = False

        if should_validate_dates and attrs.get('check_in_date') and attrs.get('check_out_date'):
            # Check if checkin is after checkout
            if attrs.get('check_in_date') >= attrs.get('check_out_date'):
                raise serializers.ValidationError("Fecha entrada debe ser anterior a fecha de salida")

            # Check if this property si reserved in this range of date
            if Reservation.objects.exclude(deleted=True
                ).filter(
                    property=property_field,
                    status__in=['approved', 'pending', 'incomplete']  # Considerar todos los estados activos
                ).filter(
                    Q(check_in_date__lt=attrs.get('check_out_date')) & Q(check_out_date__gt=attrs.get('check_in_date'))
                ).exclude(
                    id=reservation_id
                ).exists():

                raise serializers.ValidationError("Esta propiedad esta reservada en este rango de fecha")
        
        return attrs

    def create(self, validated_data):
        from decimal import Decimal
        from apps.property.pricing_models import DiscountCode
        
        # Extraer puntos a canjear antes de crear la reserva
        points_to_redeem = validated_data.pop('points_to_redeem', 0)
        
        # Extraer código de descuento si se proporciona
        discount_code = validated_data.pop('discount_code', None)
        
        # Crear la reserva
        reservation = super().create(validated_data)
        
        # Si hay código de descuento, validarlo y procesarlo
        if discount_code and discount_code.strip():
            try:
                # Buscar el código de descuento
                code_obj = DiscountCode.objects.filter(
                    code__iexact=discount_code.strip(),
                    is_active=True,
                    deleted=False
                ).first()
                
                if code_obj:
                    # Validar el código una vez más al momento de crear la reserva
                    is_valid, message = code_obj.is_valid(
                        property_id=reservation.property.id,
                        total_amount_usd=float(reservation.price_usd) if reservation.price_usd else 0,
                        booking_date=None  # Usar fecha actual para validación
                    )
                    
                    if is_valid:
                        # Guardar el código usado en la reserva
                        reservation.discount_code_used = code_obj.code
                        
                        # Incrementar el contador de uso
                        code_obj.used_count += 1
                        code_obj.save()
                        
                        reservation.save()
                        
            except Exception as e:
                # Solo logear el error, no fallar la creación de reserva
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error al procesar código de descuento: {str(e)}")
        
        # Si hay puntos para canjear, procesarlos
        if points_to_redeem and points_to_redeem > 0 and reservation.client:
            # Verificar que el cliente tenga suficientes puntos
            if reservation.client.points_balance >= Decimal(str(points_to_redeem)):
                # Descontar los puntos del cliente
                success = reservation.client.redeem_points(
                    points=points_to_redeem,
                    reservation=reservation,
                    description=f"Puntos canjeados en reserva #{reservation.id} - {reservation.property.name}"
                )
                
                if success:
                    # Guardar los puntos canjeados en la reserva
                    reservation.points_redeemed = points_to_redeem
                    reservation.save()
                else:
                    # Si no se pudieron canjear los puntos, eliminar la reserva y lanzar error
                    reservation.delete()
                    raise serializers.ValidationError("Error al canjear puntos: proceso fallido")
            else:
                # Si no tiene suficientes puntos, eliminar la reserva y lanzar error
                reservation.delete()
                raise serializers.ValidationError("Error al canjear puntos: saldo insuficiente")
        
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
    status_display = serializers.SerializerMethodField()
    
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
        price_total = float(instance.price_sol)
        adelanto_normalizado = instance.adelanto_normalizado  # Ya está en SOL
        puntos_canjeados = float(instance.points_redeemed or 0)  # Siempre en SOL (1 punto = 1 sol)
        
        # Todos los valores están en SOL, se pueden restar directamente
        resta = price_total - adelanto_normalizado - puntos_canjeados
        return '%.2f' % round(resta, 2)
    
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
    
    @extend_schema_field(serializers.CharField())
    def get_status_display(self, instance):
        return instance.get_status_display() if hasattr(instance, 'get_status_display') else 'Aprobada'


class ClientReservationSerializer(serializers.ModelSerializer):
    """Serializer para reservas creadas por clientes autenticados"""
    
    class Meta:
        model = Reservation
        fields = [
            'property', 'check_in_date', 'check_out_date', 'guests', 
            'temperature_pool', 'points_to_redeem', 'tel_contact_number',
            'price_usd', 'price_sol', 'advance_payment_currency', 'comentarios_reservas',
            'seller', 'origin', 'discount_code'
        ]
        extra_kwargs = {
            'points_to_redeem': {'write_only': True, 'required': False},
            'tel_contact_number': {'required': False},
            'price_usd': {'required': False},
            'price_sol': {'required': False},
            'advance_payment_currency': {'required': False},
            'comentarios_reservas': {'required': False},
            'seller': {'required': False},
            'origin': {'required': False},
            'discount_code': {'required': False}
        }

    points_to_redeem = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        required=False, 
        write_only=True,
        min_value=Decimal('0'),
        help_text="Puntos a canjear en esta reserva"
    )

    def validate(self, attrs):
        from django.db.models import Q
        
        # Validar fechas
        if attrs.get('check_in_date') and attrs.get('check_out_date'):
            if attrs.get('check_in_date') >= attrs.get('check_out_date'):
                raise serializers.ValidationError("Fecha entrada debe ser anterior a fecha de salida")

            # Verificar disponibilidad de la propiedad
            property_field = attrs.get('property')
            if Reservation.objects.exclude(deleted=True
                ).filter(
                    property=property_field,
                    status__in=['approved', 'pending', 'incomplete']  # Considerar aprobadas, pendientes e incompletas
                ).filter(
                    Q(check_in_date__lt=attrs.get('check_out_date')) & Q(check_out_date__gt=attrs.get('check_in_date'))
                ).exists():
                raise serializers.ValidationError("Esta propiedad no está disponible en este rango de fechas")

        # Validar canje de puntos si se especifica
        points_to_redeem = attrs.get('points_to_redeem')
        if points_to_redeem and points_to_redeem > 0:
            client = self.context.get('request').user if self.context.get('request') else None
            if not client:
                raise serializers.ValidationError("No se pudo identificar el cliente")
            
            # Verificar que el cliente tenga suficientes puntos
            available_points = client.get_available_points()
            if points_to_redeem > available_points:
                raise serializers.ValidationError(
                    f"No tienes suficientes puntos. Disponibles: {available_points}, solicitados: {points_to_redeem}"
                )

        return attrs

    def create(self, validated_data):
        from decimal import Decimal
        from apps.property.pricing_models import DiscountCode
        
        # Extraer puntos a canjear antes de crear la reserva
        points_to_redeem = validated_data.pop('points_to_redeem', 0)
        
        # Extraer código de descuento si se proporciona
        discount_code = validated_data.pop('discount_code', None)
        
        # Obtener el cliente del contexto de la request
        client = self.context['request'].user
        
        # Configurar los datos de la reserva
        validated_data['client'] = client
        
        # Verificar origin en los datos originales del request
        request_data = self.context['request'].data
        if request_data.get('origin') == 'aus':
            validated_data['origin'] = 'aus'
        else:
            validated_data['origin'] = 'client'
            
        validated_data['status'] = 'incomplete'
        
        # Asignar seller específico si se envía desde el frontend, sino usar seller por defecto (ID 14)
        if 'seller' in validated_data and validated_data['seller']:
            try:
                from apps.accounts.models import CustomUser
                seller_id = validated_data['seller']
                # Si seller_id es ya un objeto CustomUser, obtener su ID
                if hasattr(seller_id, 'id'):
                    seller_id = seller_id.id
                # Verificar que el seller existe
                seller_obj = CustomUser.objects.get(id=seller_id)
                validated_data['seller'] = seller_obj
            except (CustomUser.DoesNotExist, ValueError, TypeError):
                # Si el seller no existe o hay error, usar el seller por defecto (ID 14)
                validated_data['seller'] = CustomUser.objects.get(id=14)
        else:
            # Asignar seller por defecto (ID 14) para reservas de clientes
            validated_data['seller'] = CustomUser.objects.get(id=14)
        
        # Mantener los precios enviados desde el frontend si están presentes
        if 'price_usd' not in validated_data or not validated_data['price_usd']:
            validated_data['price_usd'] = 0
        if 'price_sol' not in validated_data or not validated_data['price_sol']:
            validated_data['price_sol'] = 0
        if 'advance_payment' not in validated_data:
            validated_data['advance_payment'] = 0
        if 'advance_payment_currency' not in validated_data:
            validated_data['advance_payment_currency'] = 'sol'
        validated_data['full_payment'] = False
        
        # Crear la reserva
        reservation = super().create(validated_data)
        
        # Si hay código de descuento, validarlo y procesarlo
        if discount_code and discount_code.strip():
            try:
                # Buscar el código de descuento
                code_obj = DiscountCode.objects.filter(
                    code__iexact=discount_code.strip(),
                    is_active=True,
                    deleted=False
                ).first()
                
                if code_obj:
                    # Validar el código una vez más al momento de crear la reserva
                    is_valid, message = code_obj.is_valid(
                        property_id=reservation.property.id,
                        total_amount_usd=float(reservation.price_usd) if reservation.price_usd else 0,
                        booking_date=None  # Usar fecha actual para validación
                    )
                    
                    if is_valid:
                        # Guardar el código usado en la reserva
                        reservation.discount_code_used = code_obj.code
                        
                        # Incrementar el contador de uso
                        code_obj.used_count += 1
                        code_obj.save()
                        
                        reservation.save()
                    else:
                        # Si el código no es válido al momento de crear la reserva, 
                        # eliminar la reserva y lanzar error
                        reservation.delete()
                        raise serializers.ValidationError(f"Error con código de descuento: {message}")
                        
            except Exception as e:
                # Si hay error procesando el código, eliminar la reserva
                reservation.delete()
                raise serializers.ValidationError(f"Error al procesar código de descuento: {str(e)}")
        
        # Si hay puntos para canjear, procesarlos INMEDIATAMENTE
        if points_to_redeem and points_to_redeem > 0:
            # Verificar que el cliente tenga suficientes puntos
            if client.points_balance >= Decimal(str(points_to_redeem)):
                # Descontar los puntos del cliente
                success = client.redeem_points(
                    points=points_to_redeem,
                    reservation=reservation,
                    description=f"Puntos canjeados en reserva #{reservation.id} - {reservation.property.name}"
                )
                
                if success:
                    # Guardar los puntos canjeados en la reserva
                    reservation.points_redeemed = points_to_redeem
                    reservation.save()
                else:
                    # Si no se pudieron canjear los puntos, eliminar la reserva y lanzar error
                    reservation.delete()
                    raise serializers.ValidationError("Error al canjear puntos: proceso fallido")
            else:
                # Si no tiene suficientes puntos, eliminar la reserva y lanzar error
                reservation.delete()
                raise serializers.ValidationError("Error al canjear puntos: saldo insuficiente")
        
        return reservation

class ReservationRetrieveSerializer(ReservationListSerializer):
    recipts = serializers.SerializerMethodField()

    @extend_schema_field(ReciptSerializer)
    def get_recipts(self, instance):
        return ReciptSerializer(
            RentalReceipt.objects.filter(reservation=instance), 
            context={'request': self.context.get('request', None)},  
            many=True
        ).data
