
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
