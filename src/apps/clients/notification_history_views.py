from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from .models import NotificationLog
from .client_auth import ClientJWTAuthentication

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_notification_history(request):
    """
    Lista el historial de notificaciones para administradores
    
    GET /api/v1/admin/push/history/
    Headers: Authorization: Bearer <jwt_token>
    
    Query params opcionales:
    - notification_type: filtrar por tipo
    - read: true/false (filtrar leídas/no leídas)
    - success: true/false (filtrar exitosas/fallidas)
    - days: número de días hacia atrás (default: 30)
    - limit: número máximo de resultados (default: 100)
    """
    user = request.user
    
    # Filtros base
    queryset = NotificationLog.objects.filter(
        admin=user,
        deleted=False
    )
    
    # Filtro por tipo de notificación
    notification_type = request.query_params.get('notification_type')
    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)
    
    # Filtro por estado de lectura
    read_param = request.query_params.get('read')
    if read_param is not None:
        is_read = read_param.lower() == 'true'
        queryset = queryset.filter(read=is_read)
    
    # Filtro por éxito/fallo
    success_param = request.query_params.get('success')
    if success_param is not None:
        is_success = success_param.lower() == 'true'
        queryset = queryset.filter(success=is_success)
    
    # Filtro por días
    days = int(request.query_params.get('days', 30))
    date_from = timezone.now() - timedelta(days=days)
    queryset = queryset.filter(sent_at__gte=date_from)
    
    # Límite
    limit = min(int(request.query_params.get('limit', 100)), 500)
    
    # Ordenar y aplicar límite
    queryset = queryset.order_by('-sent_at')[:limit]
    
    notifications = [{
        'id': str(notif.id),
        'title': notif.title,
        'body': notif.body,
        'notification_type': notif.notification_type,
        'data': notif.data,
        'device_type': notif.device_type,
        'success': notif.success,
        'error_message': notif.error_message,
        'read': notif.read,
        'read_at': notif.read_at,
        'sent_at': notif.sent_at,
    } for notif in queryset]
    
    # Estadísticas
    stats = {
        'total': len(notifications),
        'unread': sum(1 for n in notifications if not n['read']),
        'failed': sum(1 for n in notifications if not n['success'])
    }
    
    return Response({
        'success': True,
        'notifications': notifications,
        'stats': stats
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
def client_notification_history(request):
    """
    Lista el historial de notificaciones para clientes
    
    GET /api/v1/clients/push/history/
    Headers: Authorization: Bearer <client_jwt_token>
    """
    # Usar autenticación de clientes
    auth = ClientJWTAuthentication()
    try:
        user_auth_tuple = auth.authenticate(request)
        if user_auth_tuple is None:
            return Response({
                'error': 'Autenticación requerida'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client, _ = user_auth_tuple
    except Exception as e:
        return Response({
            'error': f'Error de autenticación: {str(e)}'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Filtros
    queryset = NotificationLog.objects.filter(
        client=client,
        deleted=False
    )
    
    # Filtro por tipo de notificación
    notification_type = request.query_params.get('notification_type')
    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)
    
    # Filtro por estado de lectura
    read_param = request.query_params.get('read')
    if read_param is not None:
        is_read = read_param.lower() == 'true'
        queryset = queryset.filter(read=is_read)
    
    # Filtro por días
    days = int(request.query_params.get('days', 30))
    date_from = timezone.now() - timedelta(days=days)
    queryset = queryset.filter(sent_at__gte=date_from)
    
    # Límite
    limit = min(int(request.query_params.get('limit', 100)), 500)
    
    # Ordenar y aplicar límite
    queryset = queryset.order_by('-sent_at')[:limit]
    
    notifications = [{
        'id': str(notif.id),
        'title': notif.title,
        'body': notif.body,
        'notification_type': notif.notification_type,
        'data': notif.data,
        'read': notif.read,
        'read_at': notif.read_at,
        'sent_at': notif.sent_at,
    } for notif in queryset]
    
    # Estadísticas
    stats = {
        'total': len(notifications),
        'unread': sum(1 for n in notifications if not n['read'])
    }
    
    return Response({
        'success': True,
        'notifications': notifications,
        'stats': stats
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_notification_as_read(request, notification_id):
    """
    Marca una notificación como leída (administradores)
    
    POST /api/v1/admin/push/history/<notification_id>/read/
    Headers: Authorization: Bearer <jwt_token>
    """
    user = request.user
    
    try:
        notification = NotificationLog.objects.get(
            id=notification_id,
            admin=user,
            deleted=False
        )
        
        notification.mark_as_read()
        
        return Response({
            'success': True,
            'message': 'Notificación marcada como leída'
        }, status=status.HTTP_200_OK)
        
    except NotificationLog.DoesNotExist:
        return Response({
            'error': 'Notificación no encontrada'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
def client_mark_notification_as_read(request, notification_id):
    """
    Marca una notificación como leída (clientes)
    
    POST /api/v1/clients/push/history/<notification_id>/read/
    Headers: Authorization: Bearer <client_jwt_token>
    """
    # Usar autenticación de clientes
    auth = ClientJWTAuthentication()
    try:
        user_auth_tuple = auth.authenticate(request)
        if user_auth_tuple is None:
            return Response({
                'error': 'Autenticación requerida'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client, _ = user_auth_tuple
    except Exception as e:
        return Response({
            'error': f'Error de autenticación: {str(e)}'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    try:
        notification = NotificationLog.objects.get(
            id=notification_id,
            client=client,
            deleted=False
        )
        
        notification.mark_as_read()
        
        return Response({
            'success': True,
            'message': 'Notificación marcada como leída'
        }, status=status.HTTP_200_OK)
        
    except NotificationLog.DoesNotExist:
        return Response({
            'error': 'Notificación no encontrada'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_as_read(request):
    """
    Marca todas las notificaciones como leídas (administradores)
    
    POST /api/v1/admin/push/history/mark-all-read/
    Headers: Authorization: Bearer <jwt_token>
    """
    user = request.user
    
    updated = NotificationLog.objects.filter(
        admin=user,
        read=False,
        deleted=False
    ).update(
        read=True,
        read_at=timezone.now()
    )
    
    return Response({
        'success': True,
        'message': f'{updated} notificación(es) marcada(s) como leída(s)'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def client_mark_all_as_read(request):
    """
    Marca todas las notificaciones como leídas (clientes)
    
    POST /api/v1/clients/push/history/mark-all-read/
    Headers: Authorization: Bearer <client_jwt_token>
    """
    # Usar autenticación de clientes
    auth = ClientJWTAuthentication()
    try:
        user_auth_tuple = auth.authenticate(request)
        if user_auth_tuple is None:
            return Response({
                'error': 'Autenticación requerida'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client, _ = user_auth_tuple
    except Exception as e:
        return Response({
            'error': f'Error de autenticación: {str(e)}'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    updated = NotificationLog.objects.filter(
        client=client,
        read=False,
        deleted=False
    ).update(
        read=True,
        read_at=timezone.now()
    )
    
    return Response({
        'success': True,
        'message': f'{updated} notificación(es) marcada(s) como leída(s)'
    }, status=status.HTTP_200_OK)
