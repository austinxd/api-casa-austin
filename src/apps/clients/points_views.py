
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import Clients, ClientPoints
from .serializers import (
    ClientPointsSerializer, 
    ClientPointsBalanceSerializer, 
    RedeemPointsSerializer
)


class ClientPointsBalanceView(generics.RetrieveAPIView):
    """Vista para obtener el balance de puntos del cliente"""
    serializer_class = ClientPointsBalanceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_object(self):
        # Asumiendo que tienes un método para obtener el cliente desde el token
        # Necesitarás adaptarlo según tu sistema de autenticación
        document_type = self.request.GET.get('document_type')
        number_doc = self.request.GET.get('number_doc')
        
        if not document_type or not number_doc:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("document_type y number_doc son requeridos")
        
        return get_object_or_404(
            Clients, 
            document_type=document_type, 
            number_doc=number_doc,
            deleted=False
        )


class ClientPointsHistoryView(generics.ListAPIView):
    """Vista para obtener el historial de puntos del cliente"""
    serializer_class = ClientPointsSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        document_type = self.request.GET.get('document_type')
        number_doc = self.request.GET.get('number_doc')
        
        if not document_type or not number_doc:
            return ClientPoints.objects.none()
        
        client = get_object_or_404(
            Clients, 
            document_type=document_type, 
            number_doc=number_doc,
            deleted=False
        )
        
        return ClientPoints.objects.filter(
            client=client, 
            deleted=False
        ).order_by('-created')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def redeem_points(request):
    """Endpoint para canjear puntos"""
    document_type = request.data.get('document_type')
    number_doc = request.data.get('number_doc')
    
    if not document_type or not number_doc:
        return Response(
            {"error": "document_type y number_doc son requeridos"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    client = get_object_or_404(
        Clients, 
        document_type=document_type, 
        number_doc=number_doc,
        deleted=False
    )
    
    serializer = RedeemPointsSerializer(
        data=request.data, 
        context={'client': client}
    )
    
    if serializer.is_valid():
        points_to_redeem = serializer.validated_data['points_to_redeem']
        
        # Realizar el canje
        success = client.redeem_points(
            points=points_to_redeem,
            reservation=None,  # Se puede vincular a una reserva específica si es necesario
            description=f"Canje manual de {points_to_redeem} puntos"
        )
        
        if success:
            return Response({
                "message": f"Se canjearon {points_to_redeem} puntos exitosamente",
                "remaining_points": client.get_available_points(),
                "discount_amount": float(points_to_redeem)  # 1 punto = 1 sol
            })
        else:
            return Response(
                {"error": "Error al canjear puntos"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def adjust_points_manually(request):
    """
    Endpoint para staff: agregar o retirar puntos manualmente con motivo.
    
    Body:
    {
        "client_id": "uuid-del-cliente",
        "points": 100,  // positivo para agregar, negativo para retirar
        "reason": "Bonificación especial por aniversario"
    }
    """
    from rest_framework.permissions import IsAdminUser
    from decimal import Decimal, InvalidOperation
    
    # Validar que el usuario sea staff/admin
    if not request.user.is_staff:
        return Response(
            {"error": "Solo el personal administrativo puede realizar ajustes manuales de puntos"}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Obtener datos
    client_id = request.data.get('client_id')
    points = request.data.get('points')
    reason = request.data.get('reason')
    
    # Validaciones
    if not client_id:
        return Response(
            {"error": "client_id es requerido"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if points is None:
        return Response(
            {"error": "points es requerido"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not reason or not reason.strip():
        return Response(
            {"error": "reason (motivo) es requerido"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar formato de puntos
    try:
        points_decimal = Decimal(str(points))
        if points_decimal == 0:
            return Response(
                {"error": "Los puntos no pueden ser cero"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    except (ValueError, InvalidOperation):
        return Response(
            {"error": "Formato de puntos inválido"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Buscar cliente
    client = get_object_or_404(Clients, id=client_id, deleted=False)
    
    # Validar que no se intente retirar más puntos de los disponibles
    if points_decimal < 0 and abs(points_decimal) > client.points_balance:
        return Response(
            {
                "error": f"No se pueden retirar {abs(points_decimal)} puntos. El cliente solo tiene {client.points_balance} puntos disponibles"
            }, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Realizar ajuste
    try:
        # Solo usar el primer nombre del admin
        staff_name = request.user.first_name or request.user.username
        client.adjust_points_manually(
            points=points_decimal,
            description=reason.strip(),
            staff_user=staff_name
        )
        
        action = "agregados" if points_decimal > 0 else "retirados"
        
        return Response({
            "success": True,
            "message": f"Se han {action} {abs(points_decimal)} puntos exitosamente",
            "client": {
                "id": str(client.id),
                "name": f"{client.first_name} {client.last_name}",
                "previous_balance": float(client.points_balance - points_decimal),
                "current_balance": float(client.points_balance),
                "adjustment": float(points_decimal)
            },
            "transaction": {
                "reason": reason.strip(),
                "adjusted_by": staff_name
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {"error": f"Error al realizar el ajuste: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
