import requests
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class ExpoPushService:
    """Servicio para enviar notificaciones push via Expo Push API"""
    
    @staticmethod
    def is_valid_expo_token(token: str) -> bool:
        """Valida que el token tenga el formato correcto de Expo"""
        if not token:
            return False
        return token.startswith("ExponentPushToken[") and token.endswith("]")
    
    @staticmethod
    def send_push_notification(
        to: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        badge: Optional[int] = None,
        channel_id: Optional[str] = None,
        priority: str = "default"
    ) -> Dict:
        """
        Envía una notificación push a un dispositivo específico
        
        Args:
            to: Token Expo del dispositivo (ExponentPushToken[xxx])
            title: Título de la notificación
            body: Cuerpo del mensaje
            data: Datos adicionales para la app (opcional)
            sound: Sonido de la notificación (default, null)
            badge: Número a mostrar en el ícono (iOS)
            channel_id: Canal de Android para notificaciones
            priority: Prioridad (default, normal, high)
        
        Returns:
            Dict con el resultado de la operación
        """
        if not ExpoPushService.is_valid_expo_token(to):
            return {
                "success": False,
                "error": "Invalid Expo push token format"
            }
        
        message = {
            "to": to,
            "title": title,
            "body": body,
            "sound": sound,
            "priority": priority,
        }
        
        if data:
            message["data"] = data
        
        if badge is not None:
            message["badge"] = badge
        
        if channel_id:
            message["channelId"] = channel_id
        
        try:
            response = requests.post(
                EXPO_PUSH_URL,
                json=message,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                },
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if "data" in result and result["data"]:
                ticket = result["data"]
                if ticket.get("status") == "ok":
                    logger.info(f"Push notification sent successfully to {to[:30]}...")
                    return {"success": True, "ticket": ticket}
                else:
                    error_msg = ticket.get("message", "Unknown error")
                    logger.error(f"Push notification failed: {error_msg}")
                    return {"success": False, "error": error_msg}
            
            return {"success": True, "result": result}
            
        except requests.exceptions.Timeout:
            logger.error("Expo Push API timeout")
            return {"success": False, "error": "Request timeout"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Expo Push API error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_bulk_notifications(
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        channel_id: Optional[str] = None
    ) -> Dict:
        """
        Envía notificaciones push a múltiples dispositivos
        
        Args:
            tokens: Lista de tokens Expo
            title: Título de la notificación
            body: Cuerpo del mensaje
            data: Datos adicionales
            sound: Sonido
            channel_id: Canal de Android
        
        Returns:
            Dict con resultados de envío
        """
        valid_tokens = [t for t in tokens if ExpoPushService.is_valid_expo_token(t)]
        
        if not valid_tokens:
            return {
                "success": False,
                "error": "No valid tokens provided",
                "sent": 0,
                "failed": len(tokens)
            }
        
        messages = []
        for token in valid_tokens:
            message = {
                "to": token,
                "title": title,
                "body": body,
                "sound": sound,
            }
            if data:
                message["data"] = data
            if channel_id:
                message["channelId"] = channel_id
            messages.append(message)
        
        try:
            response = requests.post(
                EXPO_PUSH_URL,
                json=messages,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                },
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            sent = 0
            failed = 0
            failed_tokens = []
            
            if "data" in result:
                for i, ticket in enumerate(result["data"]):
                    if ticket.get("status") == "ok":
                        sent += 1
                    else:
                        failed += 1
                        if i < len(valid_tokens):
                            failed_tokens.append(valid_tokens[i])
            
            logger.info(f"Bulk push: {sent} sent, {failed} failed")
            
            return {
                "success": True,
                "sent": sent,
                "failed": failed,
                "failed_tokens": failed_tokens,
                "tickets": result.get("data", [])
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Bulk push error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "sent": 0,
                "failed": len(valid_tokens)
            }
    
    @staticmethod
    def send_to_client(
        client,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default"
    ) -> Dict:
        """
        Envía notificación a todos los dispositivos de un cliente
        
        Args:
            client: Instancia del modelo Clients
            title: Título
            body: Mensaje
            data: Datos adicionales
            sound: Sonido
        
        Returns:
            Dict con resultados
        """
        from .models import PushToken
        
        tokens = PushToken.get_active_tokens_for_client(client)
        
        if not tokens.exists():
            return {
                "success": False,
                "error": "Client has no active push tokens",
                "sent": 0
            }
        
        token_list = list(tokens.values_list('expo_token', flat=True))
        result = ExpoPushService.send_bulk_notifications(
            tokens=token_list,
            title=title,
            body=body,
            data=data,
            sound=sound
        )
        
        if result.get("success"):
            tokens.update(last_used=__import__('django.utils.timezone', fromlist=['timezone']).timezone.now())
            
            if result.get("failed_tokens"):
                PushToken.objects.filter(
                    expo_token__in=result["failed_tokens"]
                ).update(failed_attempts=1)
        
        return result


class NotificationTypes:
    """Tipos de notificaciones predefinidas"""
    
    @staticmethod
    def reservation_created(reservation) -> Dict:
        """Notificación de reserva creada"""
        return {
            "title": "Reserva Confirmada",
            "body": f"Tu reserva en {reservation.property.name} ha sido creada.",
            "data": {
                "type": "reservation_created",
                "reservation_id": str(reservation.id),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def payment_approved(reservation) -> Dict:
        """Notificación de pago aprobado"""
        return {
            "title": "Pago Aprobado",
            "body": f"El pago de tu reserva en {reservation.property.name} ha sido aprobado.",
            "data": {
                "type": "payment_approved",
                "reservation_id": str(reservation.id),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def checkin_reminder(reservation) -> Dict:
        """Recordatorio de check-in"""
        return {
            "title": "Recordatorio de Check-in",
            "body": f"Mañana es tu check-in en {reservation.property.name}. ¡Te esperamos!",
            "data": {
                "type": "checkin_reminder",
                "reservation_id": str(reservation.id),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def checkout_reminder(reservation) -> Dict:
        """Recordatorio de check-out"""
        return {
            "title": "Recordatorio de Check-out",
            "body": f"Mañana es tu check-out de {reservation.property.name}. Gracias por tu visita.",
            "data": {
                "type": "checkout_reminder",
                "reservation_id": str(reservation.id),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def points_earned(client, points, reason="reserva") -> Dict:
        """Notificación de puntos ganados"""
        return {
            "title": "Puntos Ganados",
            "body": f"Has ganado {points} puntos por tu {reason}.",
            "data": {
                "type": "points_earned",
                "points": str(points),
                "screen": "Points"
            }
        }
    
    @staticmethod
    def referral_bonus(referrer_name, points) -> Dict:
        """Notificación de bono por referido"""
        return {
            "title": "Bono por Referido",
            "body": f"¡{referrer_name} usó tu código! Ganaste {points} puntos.",
            "data": {
                "type": "referral_bonus",
                "points": str(points),
                "screen": "Points"
            }
        }
    
    @staticmethod
    def welcome_discount(discount_code, percentage) -> Dict:
        """Notificación de descuento de bienvenida"""
        return {
            "title": "¡Bienvenido a Casa Austin!",
            "body": f"Usa el código {discount_code} para obtener {percentage}% de descuento en tu primera reserva.",
            "data": {
                "type": "welcome_discount",
                "discount_code": discount_code,
                "screen": "Home"
            }
        }
    
    @staticmethod
    def custom(title: str, body: str, data: Optional[Dict] = None) -> Dict:
        """Notificación personalizada"""
        return {
            "title": title,
            "body": body,
            "data": data or {"type": "custom", "screen": "Home"}
        }
