from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.clients.models import Clients
from apps.clients.auth_views import ClientJWTAuthentication
from .models import EventCategory, Event, EventRegistration
from .serializers import (
    EventCategorySerializer, EventListSerializer, EventDetailSerializer,
    EventRegistrationSerializer, EventRegistrationCreateSerializer
)


# === ENDPOINTS PÚBLICOS (sin autenticación) ===

class PublicEventCategoryListView(generics.ListAPIView):
    """Lista pública de categorías de eventos"""
    
    queryset = EventCategory.objects.filter(deleted=False)
    serializer_class = EventCategorySerializer
    permission_classes = [AllowAny]


class PublicEventListView(generics.ListAPIView):
    """Lista pública de eventos activos"""
    
    serializer_class = EventListSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        now = timezone.now()
        return Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED,
            end_date__gte=now  # Eventos que aún no han terminado (futuros + en curso)
        ).select_related('category')


class PublicEventDetailView(generics.RetrieveAPIView):
    """Detalle público de un evento específico"""
    
    serializer_class = EventDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'
    
    def get_queryset(self):
        return Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        ).select_related('category').prefetch_related('required_achievements')


# === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===

class EventRegistrationView(APIView):
    """Registrarse o cancelar registro de un evento"""
    
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    
    def post(self, request, event_id):
        """Registrarse a un evento"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            # Obtener evento
            event = Event.objects.get(
                id=event_id,
                deleted=False,
                is_active=True,
                status=Event.EventStatus.PUBLISHED
            )
            
            # Verificar si el cliente puede registrarse
            can_register, message = event.client_can_register(client)
            if not can_register:
                return Response({
                    'success': False,
                    'message': message
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear registro
            serializer = EventRegistrationCreateSerializer(
                data=request.data,
                context={'event': event, 'client': client}
            )
            if serializer.is_valid():
                registration = serializer.save()
                
                # Aprobar automáticamente si no hay restricciones especiales
                registration.status = EventRegistration.RegistrationStatus.APPROVED
                registration.save()
                
                return Response({
                    'success': True,
                    'message': 'Registro exitoso al evento',
                    'registration_id': registration.id
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Event.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Evento no encontrado'
            }, status=status.HTTP_404_NOT_FOUND)
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error al registrarse: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, event_id):
        """Cancelar registro de un evento"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            registration = EventRegistration.objects.get(
                event_id=event_id,
                client=client,
                deleted=False
            )
            
            # Solo permitir cancelar si está aprobado o pendiente
            if registration.status in [EventRegistration.RegistrationStatus.APPROVED, 
                                     EventRegistration.RegistrationStatus.PENDING]:
                registration.status = EventRegistration.RegistrationStatus.CANCELLED
                registration.save()
                
                return Response({
                    'success': True,
                    'message': 'Registro cancelado exitosamente'
                })
            else:
                return Response({
                    'success': False,
                    'message': 'No puedes cancelar este registro'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except EventRegistration.DoesNotExist:
            return Response({
                'success': False,
                'message': 'No estás registrado en este evento'
            }, status=status.HTTP_404_NOT_FOUND)
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)


class ClientEventRegistrationsView(APIView):
    """Lista de registros del cliente autenticado"""
    
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener registros del cliente autenticado"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            # Obtener registros del cliente
            registrations = EventRegistration.objects.filter(
                client=client,
                deleted=False
            ).select_related('event', 'event__category').order_by('-registration_date')
            
            serializer = EventRegistrationSerializer(registrations, many=True)
            
            return Response({
                'success': True,
                'registrations': serializer.data
            })
            
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)


# === ENDPOINT PARA VERIFICAR ELEGIBILIDAD ===

@api_view(['GET'])
@permission_classes([AllowAny])
def check_event_eligibility(request, event_id):
    """Verificar si el cliente puede registrarse a un evento específico"""
    try:
        # Autenticar cliente
        authenticator = ClientJWTAuthentication()
        auth_result = authenticator.authenticate(request)
        
        if auth_result is None:
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client, validated_token = auth_result
        
        event = Event.objects.get(
            id=event_id,
            deleted=False,
            is_active=True,
            status=Event.EventStatus.PUBLISHED
        )
        
        can_register, message = event.client_can_register(client)
        
        return Response({
            'event_id': event_id,
            'event_title': event.title,
            'can_register': can_register,
            'message': message,
            'client_requirements': {
                'current_points': float(client.points_balance),
                'required_points': float(event.min_points_required),
                'client_achievements': [
                    {'id': ach.id, 'name': ach.name} 
                    for ach in client.achievements.all()
                ],
                'required_achievements': [
                    {'id': ach.id, 'name': ach.name}
                    for ach in event.required_achievements.all()
                ]
            }
        })
        
    except Event.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Evento no encontrado'
        }, status=status.HTTP_404_NOT_FOUND)
    except (InvalidToken, TokenError):
        return Response({
            'success': False,
            'message': 'Token inválido'
        }, status=status.HTTP_401_UNAUTHORIZED)