
import os
import random
from datetime import datetime, timedelta
from twilio.rest import Client
from django.conf import settings
import logging

logger = logging.getLogger('apps')

class TwilioOTPService:
    def __init__(self):
        # Configurar con variables de entorno
        self.account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        self.auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        self.verify_sid = os.environ.get('TWILIO_VERIFY_SERVICE_SID')
        
        if not all([self.account_sid, self.auth_token, self.verify_sid]):
            logger.warning("Twilio credentials not configured. OTP service disabled.")
            self.client = None
        else:
            self.client = Client(self.account_sid, self.auth_token)
    
    def generate_otp_code(self):
        """Genera un código OTP de 6 dígitos"""
        return str(random.randint(100000, 999999))
    
    def send_otp_via_sms(self, phone_number, otp_code):
        """Envía OTP por SMS usando Twilio"""
        if not self.client:
            logger.error("Twilio client not configured")
            return False
            
        try:
            # Normalizar número de teléfono
            if not phone_number.startswith('+'):
                phone_number = f'+{phone_number}'
            
            message = self.client.messages.create(
                body=f'Tu código de verificación para Casa Austin es: {otp_code}. Válido por 10 minutos.',
                from_=os.environ.get('TWILIO_PHONE_NUMBER', '+1234567890'),
                to=phone_number
            )
            
            logger.info(f"OTP sent successfully to {phone_number}. SID: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending OTP to {phone_number}: {str(e)}")
            return False
    
    def send_otp_with_verify(self, phone_number):
        """Envía OTP usando Twilio Verify Service"""
        if not self.client:
            logger.error("Twilio client not configured")
            return False
            
        try:
            # Normalizar número de teléfono
            if not phone_number.startswith('+'):
                phone_number = f'+{phone_number}'
                
            verification = self.client.verify \
                .v2 \
                .services(self.verify_sid) \
                .verifications \
                .create(to=phone_number, channel='sms')
            
            logger.info(f"Verification sent to {phone_number}. Status: {verification.status}")
            return verification.status == 'pending'
            
        except Exception as e:
            logger.error(f"Error sending verification to {phone_number}: {str(e)}")
            return False
    
    def verify_otp_code(self, phone_number, otp_code):
        """Verifica el código OTP usando Twilio Verify"""
        if not self.client:
            logger.error("Twilio client not configured")
            return False
            
        try:
            # Normalizar número de teléfono
            if not phone_number.startswith('+'):
                phone_number = f'+{phone_number}'
                
            verification_check = self.client.verify \
                .v2 \
                .services(self.verify_sid) \
                .verification_checks \
                .create(to=phone_number, code=otp_code)
            
            logger.info(f"Verification check for {phone_number}. Status: {verification_check.status}")
            return verification_check.status == 'approved'
            
        except Exception as e:
            logger.error(f"Error verifying OTP for {phone_number}: {str(e)}")
            return False
