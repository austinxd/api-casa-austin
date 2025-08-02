
import os
from twilio.rest import Client
import logging

logger = logging.getLogger(__name__)

# Configuración de Twilio desde variables de entorno
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN') 
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

def send_sms(to_phone, message):
    """
    Envía un SMS usando Twilio
    
    Args:
        to_phone (str): Número de teléfono destino (formato: +51999999999)
        message (str): Mensaje a enviar
        
    Returns:
        dict: Resultado del envío con 'success' y 'message'
    """
    try:
        # Verificar que las credenciales estén configuradas
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            logger.warning("Credenciales de Twilio no configuradas completamente")
            return {
                'success': False,
                'message': 'Credenciales de Twilio no configuradas'
            }
        
        # Inicializar cliente de Twilio
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Enviar SMS
        message_result = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_phone
        )
        
        logger.info(f"SMS enviado exitosamente a {to_phone}. SID: {message_result.sid}")
        
        return {
            'success': True,
            'message': 'SMS enviado exitosamente',
            'sid': message_result.sid
        }
        
    except Exception as e:
        logger.error(f"Error al enviar SMS a {to_phone}: {str(e)}")
        return {
            'success': False,
            'message': f'Error al enviar SMS: {str(e)}'
        }

def send_otp_sms(phone_number, otp_code):
    """
    Envía un código OTP por SMS
    
    Args:
        phone_number (str): Número de teléfono destino
        otp_code (str): Código OTP de 6 dígitos
        
    Returns:
        dict: Resultado del envío
    """
    message = f"Tu código de verificación Casa Austin es: {otp_code}. Este código expira en 10 minutos."
    
    return send_sms(phone_number, message)

def format_phone_number(phone_number):
    """
    Formatea un número de teléfono para Twilio
    
    Args:
        phone_number (str): Número de teléfono
        
    Returns:
        str: Número formateado con código de país
    """
    # Limpiar el número de espacios y caracteres especiales, mantener solo dígitos
    phone_clean = ''.join(filter(str.isdigit, phone_number))
    
    # Si el número original ya tenía +, agregarlo de vuelta
    if phone_number.startswith('+'):
        return '+' + phone_clean
    
    # Si no tiene +, determinar el código de país
    if phone_clean.startswith('51') and len(phone_clean) >= 11:
        # Número peruano con código de país
        return '+' + phone_clean
    elif len(phone_clean) == 9:
        # Número peruano sin código de país
        return '+51' + phone_clean
    else:
        # Otros números internacionales, asumir que ya tienen código de país
        return '+' + phone_clean
    
    return phone_clean


class TwilioOTPService:
    """
    Servicio para manejo de OTP usando Twilio
    Mantiene compatibilidad con el código existente
    """
    
    def __init__(self):
        # Configurar con variables de entorno
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.verify_sid = os.getenv('TWILIO_VERIFY_SERVICE_SID')
        self.phone_number = os.getenv('TWILIO_PHONE_NUMBER')
        
        if not all([self.account_sid, self.auth_token]):
            logger.warning("Credenciales de Twilio no configuradas completamente. Servicio OTP deshabilitado.")
            self.client = None
        else:
            try:
                self.client = Client(self.account_sid, self.auth_token)
            except Exception as e:
                logger.error(f"Error al inicializar cliente Twilio: {str(e)}")
                self.client = None
    
    def generate_otp_code(self):
        """
        Genera un código OTP de 6 dígitos
        
        Returns:
            str: Código OTP de 6 dígitos
        """
        import random
        return str(random.randint(100000, 999999))
    
    def send_otp_via_sms(self, phone_number, otp_code):
        """
        Envía OTP por SMS usando Twilio
        
        Args:
            phone_number (str): Número de teléfono destino
            otp_code (str): Código OTP
            
        Returns:
            bool: True si se envió exitosamente, False en caso contrario
        """
        result = send_otp_sms(phone_number, otp_code)
        return result.get('success', False)
    
    def send_otp_with_verify(self, phone_number):
        """
        Envía OTP usando Twilio Verify Service
        
        Args:
            phone_number (str): Número de teléfono destino
            
        Returns:
            bool: True si se envió exitosamente, False en caso contrario
        """
        if not self.client or not self.verify_sid:
            logger.error("Cliente Twilio o Verify Service no configurado")
            return False
            
        try:
            # Normalizar número de teléfono
            formatted_phone = format_phone_number(phone_number)
            logger.info(f"Número original: {phone_number}, Número formateado: {formatted_phone}")
                
            verification = self.client.verify \
                .v2 \
                .services(self.verify_sid) \
                .verifications \
                .create(to=formatted_phone, channel='sms')
            
            logger.info(f"Verificación enviada a {formatted_phone}. Estado: {verification.status}")
            return verification.status == 'pending'
            
        except Exception as e:
            logger.error(f"Error al enviar verificación a {phone_number}: {str(e)}")
            return False
    
    def verify_otp_code(self, phone_number, otp_code):
        """
        Verifica el código OTP usando Twilio Verify
        
        Args:
            phone_number (str): Número de teléfono
            otp_code (str): Código OTP a verificar
            
        Returns:
            bool: True si el código es válido, False en caso contrario
        """
        if not self.client or not self.verify_sid:
            logger.error("Cliente Twilio o Verify Service no configurado")
            return False
            
        try:
            # Normalizar número de teléfono
            formatted_phone = format_phone_number(phone_number)
                
            verification_check = self.client.verify \
                .v2 \
                .services(self.verify_sid) \
                .verification_checks \
                .create(to=formatted_phone, code=otp_code)
            
            logger.info(f"Verificación de código para {formatted_phone}. Estado: {verification_check.status}")
            return verification_check.status == 'approved'
            
        except Exception as e:
            logger.error(f"Error al verificar OTP para {phone_number}: {str(e)}")
            return False
