
import os
import requests
import logging
import random

logger = logging.getLogger(__name__)

# Configuración de WhatsApp Business API desde variables de entorno
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_OTP_TEMPLATE_NAME = os.getenv('WHATSAPP_OTP_TEMPLATE_NAME')

class WhatsAppOTPService:
    """
    Servicio para manejo de OTP usando WhatsApp Business API
    """
    
    def __init__(self):
        self.access_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
        self.phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
        self.template_name = os.getenv('WHATSAPP_OTP_TEMPLATE_NAME')
        self.api_url = f"https://graph.facebook.com/v17.0/{self.phone_number_id}/messages"
        
        if not all([self.access_token, self.phone_number_id, self.template_name]):
            logger.warning("Credenciales de WhatsApp Business API no configuradas completamente. Servicio OTP deshabilitado.")
            self.enabled = False
        else:
            self.enabled = True
    
    def generate_otp_code(self):
        """
        Genera un código OTP de 6 dígitos
        
        Returns:
            str: Código OTP de 6 dígitos
        """
        return str(random.randint(100000, 999999))
    
    def format_phone_number(self, phone_number):
        """
        Formatea un número de teléfono para WhatsApp
        
        Args:
            phone_number (str): Número de teléfono
            
        Returns:
            str: Número formateado sin signos + o espacios
        """
        # Limpiar el número de espacios y caracteres especiales, mantener solo dígitos
        phone_clean = ''.join(filter(str.isdigit, phone_number))
        
        # Si no tiene código de país, agregar código peruano
        if len(phone_clean) == 9:
            phone_clean = '51' + phone_clean
        elif phone_clean.startswith('051'):
            phone_clean = phone_clean[1:]  # Remover el 0 inicial
        
        return phone_clean
    
    def send_otp_template(self, phone_number, otp_code):
        """
        Envía OTP por WhatsApp usando template
        
        Args:
            phone_number (str): Número de teléfono destino
            otp_code (str): Código OTP
            
        Returns:
            bool: True si se envió exitosamente, False en caso contrario
        """
        if not self.enabled:
            logger.error("Servicio WhatsApp no configurado correctamente")
            return False
        
        try:
            # Formatear número de teléfono
            formatted_phone = self.format_phone_number(phone_number)
            logger.info(f"Enviando OTP por WhatsApp a: {formatted_phone}")
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_phone,
                "type": "template",
                "template": {
                    "name": self.template_name,
                    "language": {
                        "code": "es"  # Código de idioma español
                    },
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {
                                    "type": "text",
                                    "text": otp_code
                                }
                            ]
                        }
                    ]
                }
            }
            
            # Log detallado para debug
            logger.info(f"WhatsApp API URL: {self.api_url}")
            logger.info(f"WhatsApp Phone Number ID: {self.phone_number_id}")
            logger.info(f"WhatsApp Template Name: {self.template_name}")
            logger.info(f"Headers: {headers}")
            logger.info(f"Payload: {payload}")
            
            response = requests.post(self.api_url, json=payload, headers=headers)
            
            logger.info(f"WhatsApp API Response Status: {response.status_code}")
            logger.info(f"WhatsApp API Response Headers: {response.headers}")
            logger.info(f"WhatsApp API Response Body: {response.text}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"WhatsApp OTP enviado exitosamente a {formatted_phone}. Response: {response_data}")
                return True
            else:
                logger.error(f"Error al enviar WhatsApp OTP a {formatted_phone}. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error al enviar WhatsApp OTP a {phone_number}: {str(e)}")
            return False
    
    def test_whatsapp_config(self):
        """
        Método de prueba para verificar la configuración de WhatsApp
        """
        logger.info("=== VERIFICACIÓN DE CONFIGURACIÓN WHATSAPP ===")
        logger.info(f"Access Token presente: {'Sí' if self.access_token else 'No'}")
        logger.info(f"Access Token (primeros 20 chars): {self.access_token[:20] if self.access_token else 'N/A'}...")
        logger.info(f"Phone Number ID: {self.phone_number_id}")
        logger.info(f"Template Name: {self.template_name}")
        logger.info(f"API URL: {self.api_url}")
        logger.info(f"Servicio habilitado: {self.enabled}")
        logger.info("============================================")
        
        # Hacer una llamada de prueba a la API para verificar permisos
        if self.enabled:
            try:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                    'Content-Type': 'application/json'
                }
                
                # URL para obtener información del número de teléfono
                test_url = f"https://graph.facebook.com/v17.0/{self.phone_number_id}"
                
                logger.info(f"Probando acceso a: {test_url}")
                response = requests.get(test_url, headers=headers)
                
                logger.info(f"Test API Response Status: {response.status_code}")
                logger.info(f"Test API Response: {response.text}")
                
                return response.status_code == 200
            except Exception as e:
                logger.error(f"Error en test de configuración: {str(e)}")
                return False
        
        return False

    def send_otp_text_message(self, phone_number, otp_code):
        """
        Envía OTP por WhatsApp usando mensaje de texto (sin template)
        
        Args:
            phone_number (str): Número de teléfono destino
            otp_code (str): Código OTP
            
        Returns:
            bool: True si se envió exitosamente, False en caso contrario
        """
        if not self.enabled:
            logger.error("Servicio WhatsApp no configurado correctamente")
            return False
        
        try:
            # Formatear número de teléfono
            formatted_phone = self.format_phone_number(phone_number)
            logger.info(f"Enviando OTP por WhatsApp (texto) a: {formatted_phone}")
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            message = f"Tu código de verificación Casa Austin es: *{otp_code}*\n\nEste código expira en 10 minutos.\n\n¡Gracias por elegirnos! 🏠"
            
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_phone,
                "type": "text",
                "text": {
                    "body": message
                }
            }
            
            response = requests.post(self.api_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"WhatsApp OTP (texto) enviado exitosamente a {formatted_phone}. Response: {response_data}")
                return True
            else:
                logger.error(f"Error al enviar WhatsApp OTP (texto) a {formatted_phone}. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error al enviar WhatsApp OTP (texto) a {phone_number}: {str(e)}")
            return False


def send_whatsapp_otp(phone_number, otp_code, use_template=True):
    """
    Función auxiliar para enviar OTP por WhatsApp
    
    Args:
        phone_number (str): Número de teléfono destino
        otp_code (str): Código OTP
        use_template (bool): Si usar template o mensaje de texto
        
    Returns:
        bool: True si se envió exitosamente
    """
    service = WhatsAppOTPService()
    
    if use_template:
        return service.send_otp_template(phone_number, otp_code)
    else:
        return service.send_otp_text_message(phone_number, otp_code)
