from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.clients.models import Clients
from apps.clients.auth_views import ClientJWTAuthentication
from .models import EventCategory, Event, EventRegistration
from .serializers import (
    EventCategorySerializer, EventListSerializer, EventDetailSerializer,
    EventRegistrationSerializer, EventRegistrationCreateSerializer, EventParticipantSerializer
)


# === ENDPOINTS PÚBLICOS (sin autenticación) ===

class PublicEventCategoryListView(generics.ListAPIView):
    """Lista pública de categorías de eventos"""
    
    queryset = EventCategory.objects.filter(deleted=False)
    serializer_class = EventCategorySerializer
    permission_classes = [AllowAny]


class PublicEventListView(generics.ListAPIView):
    """Lista pública de eventos activos con filtros opcionales"""
    
    serializer_class = EventListSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        from django.utils import timezone
        now = timezone.now()
        
        # Base queryset - todos los eventos publicados
        queryset = Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        ).select_related('category')
        
        # Filtrar por status si se proporciona
        status_filter = self.request.GET.get('status', None)
        
        if status_filter == 'upcoming':
            # Eventos próximos: que no hayan ocurrido
            queryset = queryset.filter(event_date__gte=now)
            
        elif status_filter == 'past':
            # Solo eventos que ya terminaron
            queryset = queryset.filter(event_date__lt=now)
        
        # Filtrar por categoría si se proporciona
        category_filter = self.request.GET.get('category', None)
        if category_filter:
            queryset = queryset.filter(category__name__icontains=category_filter)
        
        # Ordenar: eventos próximos por fecha ASC, pasados por fecha DESC
        if status_filter == 'upcoming':
            return queryset.order_by('event_date')  # Próximos primero
        else:
            return queryset.order_by('-event_date')  # Más recientes primero


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
            
            # Verificar si ya existe un registro (incluyendo cancelados)
            existing_registration = EventRegistration.objects.filter(
                event=event,
                client=client,
                deleted=False
            ).first()
            
            if existing_registration:
                # Reutilizar registro existente si está cancelado o rechazado
                if existing_registration.status in ['cancelled', 'rejected']:
                    existing_registration.status = EventRegistration.RegistrationStatus.APPROVED
                    existing_registration.registration_date = timezone.now()
                    existing_registration.save()
                    
                    return Response({
                        'success': True,
                        'message': 'Registro reactivado exitosamente',
                        'registration_id': existing_registration.id
                    }, status=status.HTTP_201_CREATED)
                else:
                    # Si está pending o approved, no debería llegar aquí por client_can_register
                    return Response({
                        'success': False,
                        'message': 'Ya tienes un registro activo para este evento'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear nuevo registro si no existe
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
@authentication_classes([])  # Deshabilita autenticación automática de DRF
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
                    {'id': ach.achievement.id, 'name': ach.achievement.name} 
                    for ach in client.achievements.filter(deleted=False).select_related('achievement')
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
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EventParticipantsView(APIView):
    """Endpoint para mostrar participantes de un evento"""
    
    permission_classes = [AllowAny]  # Público para mostrar participantes
    
    def get(self, request, event_id):
        """
        GET /api/v1/events/{event_id}/participants/
        
        Muestra todos los participantes aprobados de un evento con:
        - Foto de perfil (prioriza Facebook, luego custom)
        - Nombre formateado (Augusto T.)
        - Nivel más alto con icono
        """
        try:
            # Obtener evento
            event = Event.objects.get(id=event_id, deleted=False)
            
            # Obtener solo participantes aprobados
            participants = EventRegistration.objects.filter(
                event=event,
                status=EventRegistration.RegistrationStatus.APPROVED,
                deleted=False
            ).select_related('client').prefetch_related(
                'client__achievements__achievement',
                'client__event_registrations'
            ).order_by('-registration_date')
            
            # Serializar datos
            serializer = EventParticipantSerializer(
                participants, 
                many=True, 
                context={'request': request}
            )
            
            return Response({
                'success': True,
                'event': {
                    'id': event.id,
                    'title': event.title,
                    'registered_users': participants.count(),
                    'max_allowed_users': event.max_participants,
                    'available_spots': event.available_spots,
                    'event_status': self._get_event_status(event)
                },
                'participants': serializer.data
            })
            
        except Event.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Evento no encontrado'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error interno: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_event_status(self, event):
        """Helper para obtener el estado del evento"""
        from django.utils import timezone
        now = timezone.now()
        
        if event.event_date > now:
            return 'upcoming'  # Próximo
        else:
            return 'past'      # Pasado