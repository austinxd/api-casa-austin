
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
    # Remover espacios y caracteres especiales
    phone_clean = ''.join(filter(str.isdigit, phone_number))
    
    # Si no tiene código de país, agregar +51 (Perú)
    if not phone_number.startswith('+'):
        if phone_clean.startswith('51'):
            phone_clean = '+' + phone_clean
        elif len(phone_clean) == 9:
            phone_clean = '+51' + phone_clean
        else:
            phone_clean = '+' + phone_clean
    
    return phone_clean
