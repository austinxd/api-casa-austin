from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db.models import Q
from datetime import datetime
from decimal import Decimal

from .models import Property
from apps.reservation.models import Reservation
from apps.clients.models import Clients as Client
from .pricing_service import PricingCalculationService
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.core.exceptions import ValidationError
from django.conf import settings


class CalculatePricingERPAPIView(APIView):
    """
    Endpoint para calcular precios con búsqueda de opciones moviendo reservas
    GET /api/v1/properties/calculate-pricing-erp/
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='check_in_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Fecha de check-in (YYYY-MM-DD)',
                required=True
            ),
            OpenApiParameter(
                name='check_out_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Fecha de check-out (YYYY-MM-DD)',
                required=True
            ),
            OpenApiParameter(
                name='guests',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Número de huéspedes (por defecto: 1)',
                required=False
            ),
            OpenApiParameter(
                name='client_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='UUID del cliente (opcional)',
                required=False
            ),
        ],
        responses={
            200: {
                'description': 'Cálculo exitoso con opciones disponibles y movimientos sugeridos',
                'type': 'object'
            },
            400: 'Bad Request - Parámetros inválidos'
        },
        description='Calcula precios y busca opciones moviendo reservas cuando no hay disponibilidad directa'
    )
    def get(self, request):
        try:
            check_in_date_str = request.query_params.get('check_in_date')
            check_out_date_str = request.query_params.get('check_out_date')
            guests_str = request.query_params.get('guests')
            client_id = request.query_params.get('client_id')

            if not all([check_in_date_str, check_out_date_str]):
                return Response({
                    'error': 1,
                    'error_message': 'Parámetros requeridos: check_in_date, check_out_date'
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                check_in_date = datetime.strptime(check_in_date_str, '%Y-%m-%d').date()
                check_out_date = datetime.strptime(check_out_date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'error': 2,
                    'error_message': 'Formato de fecha inválido. Use YYYY-MM-DD'
                }, status=status.HTTP_400_BAD_REQUEST)

            if check_in_date < datetime.now().date():
                return Response({
                    'error': 8,
                    'error_message': 'La fecha de entrada no puede ser en el pasado'
                }, status=status.HTTP_400_BAD_REQUEST)

            if check_out_date <= check_in_date:
                return Response({
                    'error': 9,
                    'error_message': 'La fecha de salida debe ser posterior a la fecha de entrada'
                }, status=status.HTTP_400_BAD_REQUEST)

            guests = 1
            if guests_str:
                try:
                    guests = int(guests_str)
                    if guests < 1:
                        raise ValueError()
                except ValueError:
                    return Response({
                        'error': 3,
                        'error_message': 'El número de huéspedes debe ser un entero mayor a 0'
                    }, status=status.HTTP_400_BAD_REQUEST)

            if client_id:
                try:
                    from uuid import UUID
                    UUID(client_id)
                    if not Client.objects.filter(id=client_id, deleted=False).exists():
                        return Response({
                            'error': 6,
                            'error_message': 'Cliente no encontrado'
                        }, status=status.HTTP_404_NOT_FOUND)
                except ValueError:
                    return Response({
                        'error': 7,
                        'error_message': 'client_id debe ser un UUID válido'
                    }, status=status.HTTP_400_BAD_REQUEST)

            pricing_service = PricingCalculationService()
            
            all_properties = Property.objects.filter(deleted=False).order_by('name')
            
            direct_available = []
            unavailable_properties = []
            
            for property in all_properties:
                pricing_data = pricing_service._calculate_property_pricing(
                    property=property,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    nights=(check_out_date - check_in_date).days,
                    client=Client.objects.filter(id=client_id, deleted=False).first() if client_id else None,
                    discount_code=None,
                    additional_services_ids=None
                )
                
                if pricing_data['available']:
                    direct_available.append({
                        **pricing_data,
                        'option_type': 'direct'
                    })
                else:
                    conflicting_reservations = Reservation.objects.filter(
                        property=property,
                        deleted=False,
                        status__in=['approved', 'pending', 'incomplete', 'under_review']
                    ).filter(
                        Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
                    ).select_related('client')
                    
                    unavailable_properties.append({
                        'property_id': str(property.id),
                        'property_name': property.name,
                        'conflicting_reservations': [
                            {
                                'reservation_id': str(res.id),
                                'client_name': f"{res.client.first_name} {res.client.last_name}" if res.client else "Sin cliente",
                                'check_in': res.check_in_date.strftime('%Y-%m-%d'),
                                'check_out': res.check_out_date.strftime('%Y-%m-%d'),
                                'status': res.status,
                                'nights': (res.check_out_date - res.check_in_date).days
                            }
                            for res in conflicting_reservations
                        ]
                    })
            
            movement_options = []
            
            for unavailable_prop in unavailable_properties:
                for conflicting_res in unavailable_prop['conflicting_reservations']:
                    res_check_in = datetime.strptime(conflicting_res['check_in'], '%Y-%m-%d').date()
                    res_check_out = datetime.strptime(conflicting_res['check_out'], '%Y-%m-%d').date()
                    res_nights = conflicting_res['nights']
                    
                    for target_property in all_properties:
                        if str(target_property.id) == unavailable_prop['property_id']:
                            continue
                        
                        target_available = not Reservation.objects.filter(
                            property=target_property,
                            deleted=False,
                            status__in=['approved', 'pending', 'incomplete', 'under_review']
                        ).filter(
                            Q(check_in_date__lt=res_check_out) & Q(check_out_date__gt=res_check_in)
                        ).exists()
                        
                        if target_available:
                            original_property = Property.objects.get(id=unavailable_prop['property_id'])
                            
                            new_pricing = pricing_service._calculate_property_pricing(
                                property=original_property,
                                check_in_date=check_in_date,
                                check_out_date=check_out_date,
                                guests=guests,
                                nights=(check_out_date - check_in_date).days,
                                client=Client.objects.filter(id=client_id, deleted=False).first() if client_id else None,
                                discount_code=None,
                                additional_services_ids=None
                            )
                            
                            movement_options.append({
                                **new_pricing,
                                'option_type': 'move_required',
                                'movement_required': {
                                    'reservation_id': conflicting_res['reservation_id'],
                                    'client_name': conflicting_res['client_name'],
                                    'from_property': unavailable_prop['property_name'],
                                    'to_property': target_property.name,
                                    'reservation_dates': {
                                        'check_in': conflicting_res['check_in'],
                                        'check_out': conflicting_res['check_out'],
                                        'nights': res_nights
                                    },
                                    'status': conflicting_res['status']
                                }
                            })
                            break
            
            return Response({
                'success': True,
                'error': 0,
                'data': {
                    'requested_dates': {
                        'check_in': check_in_date.strftime('%Y-%m-%d'),
                        'check_out': check_out_date.strftime('%Y-%m-%d'),
                        'nights': (check_out_date - check_in_date).days,
                        'guests': guests
                    },
                    'direct_available': direct_available,
                    'options_with_movements': movement_options,
                    'summary': {
                        'total_direct_available': len(direct_available),
                        'total_options_with_movements': len(movement_options),
                        'total_properties_checked': len(all_properties)
                    }
                },
                'message': 'Búsqueda de disponibilidad completada'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'error': 10,
                'error_message': 'Error interno del servidor',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
