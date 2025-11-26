import requests
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class ExpoPushService:
    """Servicio para enviar notificaciones push via Expo Push API"""
    
    @staticmethod
    def _log_notification(recipient, title, body, notification_type, data, expo_token, device_type, success, error_message=None):
        """
        Helper interno para registrar notificaciones en el historial
        Importa NotificationLog aquí para evitar imports circulares
        """
        try:
            from .models import NotificationLog
            NotificationLog.log_notification(
                recipient=recipient,
                title=title,
                body=body,
                notification_type=notification_type,
                data=data,
                expo_token=expo_token,
                device_type=device_type,
                success=success,
                error_message=error_message
            )
        except Exception as e:
            logger.error(f"Error al registrar notificación en historial: {str(e)}")
    
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
    
    @staticmethod
    def send_to_admins(
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        user_filter=None
    ) -> Dict:
        """
        Envía notificación a todos los administradores con tokens activos
        
        Args:
            title: Título
            body: Mensaje
            data: Datos adicionales
            sound: Sonido
            user_filter: Filtrar a un usuario específico (opcional)
        
        Returns:
            Dict con resultados
        """
        from .models import AdminPushToken
        
        if user_filter:
            tokens = AdminPushToken.get_active_tokens_for_user(user_filter)
        else:
            tokens = AdminPushToken.get_all_active_admin_tokens()
        
        if not tokens.exists():
            logger.warning("⚠️ No hay tokens de administradores activos para enviar notificación")
            return {
                "success": False,
                "error": "No active admin push tokens",
                "sent": 0
            }
        
        token_list = list(tokens.values_list('expo_token', flat=True))
        logger.info(f"📱 Enviando notificación push a {len(token_list)} administrador(es)")
        
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
                failed_tokens_list = result["failed_tokens"]
                for token in AdminPushToken.objects.filter(expo_token__in=failed_tokens_list):
                    token.mark_as_failed()
        
        return result


class NotificationTypes:
    """Tipos de notificaciones predefinidas con información detallada"""
    
    @staticmethod
    def _format_date(date_obj) -> str:
        """Formatea fecha en español"""
        if not date_obj:
            return ""
        months = {
            1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
            5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
            9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
        }
        return f"{date_obj.day} de {months.get(date_obj.month, '')} del {date_obj.year}"
    
    @staticmethod
    def _format_price(price) -> str:
        """Formatea precio en dólares"""
        if price:
            return f"${float(price):,.2f}"
        return "$0.00"
    
    @staticmethod
    def reservation_created(reservation) -> Dict:
        """Notificación detallada de reserva creada"""
        check_in = NotificationTypes._format_date(reservation.check_in_date)
        check_out = NotificationTypes._format_date(reservation.check_out_date)
        price = NotificationTypes._format_price(reservation.price_usd)
        guests = reservation.guests or 1
        
        body = (
            f"Tu reserva en {reservation.property.name} ha sido creada.\n"
            f"Fechas: {check_in} al {check_out}\n"
            f"Huéspedes: {guests} persona{'s' if guests > 1 else ''}\n"
            f"Total: {price} USD"
        )
        
        return {
            "title": "Reserva Confirmada",
            "body": body,
            "data": {
                "type": "reservation_created",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "check_in": str(reservation.check_in_date),
                "check_out": str(reservation.check_out_date),
                "guests": guests,
                "price_usd": str(reservation.price_usd),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def payment_approved(reservation) -> Dict:
        """Notificación detallada de pago aprobado"""
        check_in = NotificationTypes._format_date(reservation.check_in_date)
        price = NotificationTypes._format_price(reservation.price_usd)
        
        body = (
            f"El pago de tu reserva en {reservation.property.name} ha sido aprobado.\n"
            f"Monto: {price} USD\n"
            f"Check-in: {check_in}\n"
            f"¡Te esperamos!"
        )
        
        return {
            "title": "Pago Aprobado",
            "body": body,
            "data": {
                "type": "payment_approved",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "check_in": str(reservation.check_in_date),
                "price_usd": str(reservation.price_usd),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def checkin_reminder(reservation) -> Dict:
        """Recordatorio detallado de check-in"""
        check_in = NotificationTypes._format_date(reservation.check_in_date)
        guests = reservation.guests or 1
        
        body = (
            f"Mañana es tu check-in en {reservation.property.name}.\n"
            f"Fecha: {check_in}\n"
            f"Hora de llegada: desde las 3:00 PM\n"
            f"Huéspedes: {guests} persona{'s' if guests > 1 else ''}\n"
            f"¡Te esperamos!"
        )
        
        return {
            "title": "Recordatorio de Check-in",
            "body": body,
            "data": {
                "type": "checkin_reminder",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "check_in": str(reservation.check_in_date),
                "guests": guests,
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def checkout_reminder(reservation) -> Dict:
        """Recordatorio detallado de check-out"""
        check_out = NotificationTypes._format_date(reservation.check_out_date)
        late_checkout = getattr(reservation, 'late_checkout', False)
        checkout_time = "1:00 PM" if late_checkout else "11:00 AM"
        
        body = (
            f"Mañana es tu check-out de {reservation.property.name}.\n"
            f"Fecha: {check_out}\n"
            f"Hora límite: {checkout_time}\n"
            f"Gracias por tu visita. ¡Esperamos verte pronto!"
        )
        
        return {
            "title": "Recordatorio de Check-out",
            "body": body,
            "data": {
                "type": "checkout_reminder",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "check_out": str(reservation.check_out_date),
                "late_checkout": late_checkout,
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def points_earned(client, points, reservation=None, reason="reserva") -> Dict:
        """Notificación detallada de puntos ganados"""
        balance = float(client.points_balance) if client.points_balance else 0
        
        if reservation:
            property_name = reservation.property.name if reservation.property else ""
            body = (
                f"¡Has ganado {points} puntos por tu {reason} en {property_name}!\n"
                f"Tu balance actual: {balance:.0f} puntos\n"
                f"Usa tus puntos en tu próxima reserva."
            )
        else:
            body = (
                f"¡Has ganado {points} puntos por tu {reason}!\n"
                f"Tu balance actual: {balance:.0f} puntos\n"
                f"Usa tus puntos en tu próxima reserva."
            )
        
        return {
            "title": "¡Puntos Ganados!",
            "body": body,
            "data": {
                "type": "points_earned",
                "points": str(points),
                "balance": str(balance),
                "reason": reason,
                "screen": "Points"
            }
        }
    
    @staticmethod
    def referral_bonus(referred_client, points, referrer_client=None) -> Dict:
        """Notificación detallada de bono por referido"""
        referred_name = referred_client.first_name if hasattr(referred_client, 'first_name') else str(referred_client)
        balance = float(referrer_client.points_balance) if referrer_client and referrer_client.points_balance else 0
        
        body = (
            f"¡{referred_name} usó tu código de referido!\n"
            f"Has ganado {points} puntos de bonificación.\n"
            f"Tu balance actual: {balance:.0f} puntos\n"
            f"Sigue compartiendo tu código para ganar más."
        )
        
        return {
            "title": "¡Bono por Referido!",
            "body": body,
            "data": {
                "type": "referral_bonus",
                "points": str(points),
                "balance": str(balance),
                "referred_name": referred_name,
                "screen": "Points"
            }
        }
    
    @staticmethod
    def welcome_discount(client, discount_code, percentage, valid_until=None) -> Dict:
        """Notificación detallada de descuento de bienvenida"""
        client_name = client.first_name if hasattr(client, 'first_name') else "Nuevo usuario"
        
        if valid_until:
            valid_date = NotificationTypes._format_date(valid_until)
            body = (
                f"¡Bienvenido a Casa Austin, {client_name}!\n"
                f"Tienes un descuento exclusivo del {percentage}% en tu primera reserva.\n"
                f"Código: {discount_code}\n"
                f"Válido hasta: {valid_date}\n"
                f"¡Reserva ahora y disfruta!"
            )
        else:
            body = (
                f"¡Bienvenido a Casa Austin, {client_name}!\n"
                f"Tienes un descuento exclusivo del {percentage}% en tu primera reserva.\n"
                f"Código: {discount_code}\n"
                f"¡Reserva ahora y disfruta!"
            )
        
        return {
            "title": "¡Bienvenido a Casa Austin!",
            "body": body,
            "data": {
                "type": "welcome_discount",
                "discount_code": discount_code,
                "percentage": str(percentage),
                "valid_until": str(valid_until) if valid_until else None,
                "screen": "Home"
            }
        }
    
    @staticmethod
    def payment_pending(reservation) -> Dict:
        """Notificación detallada de pago pendiente"""
        check_in = NotificationTypes._format_date(reservation.check_in_date)
        price = NotificationTypes._format_price(reservation.price_usd)
        
        body = (
            f"Tu reserva en {reservation.property.name} está pendiente de pago.\n"
            f"Monto: {price} USD\n"
            f"Check-in: {check_in}\n"
            f"Completa tu pago para confirmar la reserva."
        )
        
        return {
            "title": "Pago Pendiente",
            "body": body,
            "data": {
                "type": "payment_pending",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "price_usd": str(reservation.price_usd),
                "screen": "ReservationDetail"
            }
        }
    
    @staticmethod
    def reservation_cancelled(reservation, reason=None) -> Dict:
        """Notificación detallada de reserva cancelada"""
        check_in = NotificationTypes._format_date(reservation.check_in_date)
        
        if reason:
            body = (
                f"Tu reserva en {reservation.property.name} ha sido cancelada.\n"
                f"Fecha original: {check_in}\n"
                f"Motivo: {reason}\n"
                f"Contáctanos si tienes preguntas."
            )
        else:
            body = (
                f"Tu reserva en {reservation.property.name} ha sido cancelada.\n"
                f"Fecha original: {check_in}\n"
                f"Contáctanos si tienes preguntas."
            )
        
        return {
            "title": "Reserva Cancelada",
            "body": body,
            "data": {
                "type": "reservation_cancelled",
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "reason": reason,
                "screen": "Reservations"
            }
        }
    
    @staticmethod
    def event_winner(client, event, position) -> Dict:
        """Notificación detallada de ganador de evento"""
        positions = {1: "primer", 2: "segundo", 3: "tercer"}
        position_text = positions.get(position, f"{position}°")
        
        body = (
            f"¡Felicitaciones {client.first_name}!\n"
            f"Has ganado el {position_text} lugar en el evento '{event.name}'.\n"
            f"Pronto te contactaremos para coordinar tu premio.\n"
            f"¡Gracias por participar!"
        )
        
        return {
            "title": "¡Ganaste el Evento!",
            "body": body,
            "data": {
                "type": "event_winner",
                "event_id": str(event.id),
                "event_name": event.name,
                "position": position,
                "screen": "Events"
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
