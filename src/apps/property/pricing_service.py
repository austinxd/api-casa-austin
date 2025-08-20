from decimal import Decimal
from datetime import date, timedelta
from django.db.models import Q
from django.utils import timezone

from .models import Property
from .pricing_models import (
    ExchangeRate,
    SeasonPricing,
    SpecialDatePricing,
    DiscountCode,
    AdditionalService,
    CancellationPolicy,
    AutomaticDiscount,
    PropertyPricing
)
from apps.clients.models import Clients
from apps.reservation.models import Reservation


class PricingCalculationService:

    def __init__(self):
        self.exchange_rate = ExchangeRate.get_current_rate()

    def calculate_pricing(self, check_in_date, check_out_date, guests, property_id=None, client_id=None, discount_code=None):
        """Calcula precios para una o todas las propiedades"""

        # Validaciones básicas
        if check_in_date >= check_out_date:
            raise ValueError("La fecha de salida debe ser posterior a la fecha de entrada")

        if check_in_date < date.today():
            raise ValueError("La fecha de entrada no puede ser en el pasado")

        nights = (check_out_date - check_in_date).days

        # Validar requisitos de fechas especiales ANTES de cualquier cálculo
        if property_id:
            property_obj = Property.objects.filter(id=property_id, deleted=False).first()
            if property_obj:
                self._validate_special_date_requirements(property_obj, check_in_date, check_out_date, nights)
        else:
            # Si no hay property_id específico, validar para todas las propiedades disponibles
            properties_to_validate = Property.objects.filter(deleted=False)
            for prop in properties_to_validate:
                self._validate_special_date_requirements(prop, check_in_date, check_out_date, nights)

        # Obtener cliente si se proporciona
        client = None
        if client_id:
            try:
                client = Clients.objects.get(id=client_id, deleted=False)
            except Clients.DoesNotExist:
                pass

        # Obtener propiedades
        if property_id:
            properties = Property.objects.filter(id=property_id, deleted=False)
        else:
            properties = Property.objects.filter(deleted=False)

        results = []

        for property in properties:
            property_pricing = self._calculate_property_pricing(
                property, check_in_date, check_out_date, guests, nights, client, discount_code
            )
            results.append(property_pricing)

        # Ordenar los resultados por nombre de propiedad de forma numérica
        def sort_key(prop):
            name = prop['property_name'].lower()
            # Extraer el número al final del nombre si existe
            import re
            match = re.search(r'(\d+)$', name)
            if match:
                # Si tiene número al final, usar ese número para ordenar
                base_name = re.sub(r'\s*\d+$', '', name)
                number = int(match.group(1))
                return (base_name, number)
            else:
                # Si no tiene número, ordenar alfabéticamente
                return (name, 0)
        
        results.sort(key=sort_key)

        # Generar mensajes contextuales para chatbot
        chatbot_messages = self._generate_chatbot_messages(
            results, check_in_date, check_out_date, guests, nights, client, property_id
        )

        # Información general (solo incluir client_info si se proporciona client_id)
        general_info = {
            'totalCasasDisponibles': chatbot_messages['estado_disponibilidad'],
            'check_in_date': check_in_date,
            'check_out_date': check_out_date,
            'guests': guests,
            'total_nights': nights,
            'exchange_rate': round(float(self.exchange_rate), 2),
            'properties': results,
            'general_recommendations': self._get_general_recommendations(results, guests, nights),
            # Mensajes para chatbot
            'message1': chatbot_messages['message1'],
            'message2': chatbot_messages['message2']
        }
        
        # Solo incluir client_info si se proporciona un client_id
        if client_id:
            general_info['client_info'] = self._get_client_info(client)

        return general_info

    def _calculate_property_pricing(self, property, check_in_date, check_out_date, guests, nights, client, discount_code):
        """Calcula precios para una propiedad específica"""

        # Verificar disponibilidad
        available, availability_message = self._check_availability(property, check_in_date, check_out_date)

        # Obtener precios noche por noche (ya incluye huéspedes adicionales)
        nightly_prices, subtotal_usd = self._get_nightly_prices(property, check_in_date, check_out_date, guests)

        # Calcular precio base (sin huéspedes adicionales) para mostrar desglose
        _, base_total_usd = self._get_nightly_prices(property, check_in_date, check_out_date, 1)

        # Calcular precio por personas extra
        extra_guests = max(0, guests - 1)  # Después de la primera persona
        extra_person_price_per_night_usd = property.precio_extra_persona or Decimal('0.00')
        extra_person_price_usd = extra_person_price_per_night_usd  # Precio por noche por persona adicional
        extra_person_total_usd = extra_person_price_per_night_usd * extra_guests * nights  # Total por todas las noches y personas extra

        # Aplicar descuentos
        discount_applied = self._apply_discounts(
            property, subtotal_usd, subtotal_usd * self.exchange_rate, nights, guests, discount_code, client, check_in_date
        )

        final_price_usd = subtotal_usd - Decimal(str(discount_applied['discount_amount_usd']))
        final_price_sol = (subtotal_usd * self.exchange_rate) - Decimal(str(discount_applied['discount_amount_sol']))

        


        # Convertir a soles
        base_price_sol = base_total_usd * self.exchange_rate
        extra_person_price_sol = extra_person_price_usd * self.exchange_rate
        extra_person_total_sol = extra_person_total_usd * self.exchange_rate
        subtotal_sol = subtotal_usd * self.exchange_rate
        #final_price_sol = final_price_usd * self.exchange_rate # Ya calculado arriba

        # Servicios adicionales
        additional_services = self._get_additional_services(property, nights, guests)

        # Política de cancelación
        cancellation_policy = CancellationPolicy.get_applicable_policy(property.id)

        # Beneficios del cliente
        client_benefits = self._get_client_benefits(client, property)

        # Recomendaciones específicas
        recommendations = self._get_property_recommendations(
            property, guests, nights, subtotal_usd, available
        )

        # Construir respuesta base
        response = {
            'property_id': property.id,
            'property_name': property.name,
            'property_slug': property.slug,
            'base_price_usd': round(float(base_total_usd), 2),
            'base_price_sol': round(float(base_price_sol), 2),
            'extra_person_price_per_night_usd': round(float(extra_person_price_usd), 2),
            'extra_person_price_per_night_sol': round(float(extra_person_price_sol), 2),
            'extra_person_total_usd': round(float(extra_person_total_usd), 2),
            'extra_person_total_sol': round(float(extra_person_total_sol), 2),
            'total_nights': nights,
            'total_guests': guests,
            'extra_guests': extra_guests,
            'subtotal_usd': round(float(subtotal_usd), 2),
            'subtotal_sol': round(float(subtotal_sol), 2),
            'final_price_usd': round(float(final_price_usd), 2),
            'final_price_sol': round(float(final_price_sol), 2),
            'available': available,
            'availability_message': availability_message,
            'additional_services': additional_services,
            'cancellation_policy': cancellation_policy,
            'recommendations': recommendations
        }

        # Solo incluir discount_applied si hay descuento aplicado o si se proporcionó un código
        if discount_applied['type'] != 'none' or discount_code:
            discount_applied.update({
                'discount_amount_usd': round(float(discount_applied['discount_amount_usd']), 2),
                'discount_amount_sol': round(float(discount_applied['discount_amount_sol']), 2)
            })
            response['discount_applied'] = discount_applied

        # Solo incluir client_benefits si hay un cliente
        if client:
            response['client_benefits'] = client_benefits

        return response

    def _check_availability(self, property, check_in_date, check_out_date):
        """Verifica disponibilidad de la propiedad"""
        conflicting_reservations = Reservation.objects.filter(
            property=property,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete']
        ).filter(
            Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
        )

        if conflicting_reservations.exists():
            return False, "Propiedad no disponible para las fechas seleccionadas"

        return True, "Propiedad disponible"

    def _get_nightly_prices(self, property, check_in_date, check_out_date, guests=1):
        """Obtiene precios noche por noche considerando temporadas, tipo de día y fechas especiales"""
        from datetime import timedelta

        current_date = check_in_date
        nightly_prices = []
        total_price = Decimal('0.00')

        while current_date < check_out_date:
            night_price = self._get_price_for_specific_date(property, current_date, guests)
            nightly_prices.append({
                'date': current_date,
                'price': night_price,
                'price_base': self._get_price_for_specific_date(property, current_date, 1),
                'guests': guests,
                'type': self._get_date_type(current_date)
            })
            total_price += night_price
            current_date += timedelta(days=1)

        return nightly_prices, total_price

    def _get_price_for_specific_date(self, property, date, guests=1):
        """Obtiene el precio para una fecha específica incluyendo huéspedes adicionales"""
        # 1. Verificar si hay precio especial para esta fecha
        special_pricing = SpecialDatePricing.objects.filter(
            property=property,
            month=date.month,
            day=date.day,
            is_active=True
        ).first()

        if special_pricing:
            return special_pricing.calculate_total_price(guests)

        # 2. Buscar precio según PropertyPricing
        try:
            property_pricing = PropertyPricing.objects.get(property=property, deleted=False)
            return property_pricing.calculate_total_price_for_date(date, guests)
        except PropertyPricing.DoesNotExist:
            # 3. Verificar si está en temporada alta usando el nuevo sistema
            if SeasonPricing.is_high_season(date):
                # Usar precio base de la propiedad con incremento por temporada alta
                base_price = property.precio_desde or Decimal('100.00')
                base_price = base_price * Decimal('1.5')  # 50% más en temporada alta
            else:
                base_price = property.precio_desde or Decimal('100.00')

            # Calcular precio por huéspedes adicionales  
            if guests > 1 and property.precio_extra_persona:
                additional_guests = guests - 1
                additional_cost = property.precio_extra_persona * additional_guests
                return base_price + additional_cost

            return base_price

    def _get_date_type(self, date):
        """Determina el tipo de fecha"""
        # Verificar si es fecha especial
        if SpecialDatePricing.objects.filter(month=date.month, day=date.day, is_active=True).exists():
            special = SpecialDatePricing.objects.filter(month=date.month, day=date.day, is_active=True).first()
            return f"Fecha Especial: {special.description}"

        # Verificar tipo de día
        weekday = date.weekday()
        if weekday >= 4:  # Viernes, Sábado, Domingo
            return "Fin de semana"
        else:
            return "Día de semana"

    def _apply_discounts(self, property, subtotal_usd, subtotal_sol, nights, guests, discount_code, client, check_in_date):
        """Aplica descuentos automáticos o códigos de descuento"""
        
        # Si no hay código de descuento ni cliente, no procesar descuentos
        if not discount_code and not client:
            return {
                'type': 'none',
                'description': 'Sin descuento',
                'discount_percentage': 0,
                'discount_amount_usd': Decimal('0.00'),
                'discount_amount_sol': Decimal('0.00'),
                'code_used': None
            }
            
        discount_info = {
            'type': 'none',
            'description': 'Sin descuento',
            'discount_percentage': 0,
            'discount_amount_usd': Decimal('0.00'),
            'discount_amount_sol': Decimal('0.00'),
            'code_used': None
        }

        # Si hay código de descuento, verificar y aplicar
        if discount_code and discount_code.strip():
            try:
                # Limpiar el código y convertir a mayúsculas
                clean_code = discount_code.strip().upper()
                
                # Buscar el código de descuento con búsqueda case-insensitive
                code = DiscountCode.objects.filter(
                    code__iexact=clean_code, 
                    is_active=True, 
                    deleted=False
                ).first()
                
                if not code:
                    # Debug: listar códigos disponibles
                    available_codes = DiscountCode.objects.filter(
                        is_active=True, 
                        deleted=False
                    ).values_list('code', flat=True)
                    print(f"DEBUG: Código '{clean_code}' no encontrado. Códigos disponibles: {list(available_codes)}")
                    
                    discount_info.update({
                        'type': 'error',
                        'description': f"Código '{clean_code}' no encontrado",
                        'discount_percentage': 0,
                        'discount_amount_usd': 0.00,
                        'discount_amount_sol': 0.00,
                        'code_used': clean_code
                    })
                    return discount_info
                
                # Debug logging
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Validando código {code.code} para propiedad {property.name} (ID: {property.id})")
                logger.info(f"Propiedades asignadas al código: {list(code.properties.values_list('name', flat=True))}")
                
                is_valid, message = code.is_valid(property.id, subtotal_usd, None)  # Usar None para validar con fecha actual
                logger.info(f"Resultado validación: {is_valid} - {message}")

                if is_valid:
                    discount_amount_usd = code.calculate_discount(subtotal_usd)
                    discount_info.update({
                        'type': 'discount_code',
                        'description': f"Código: {code.code} - {code.description}",
                        'discount_percentage': float(code.discount_value) if code.discount_type == 'percentage' else 0,
                        'discount_amount_usd': discount_amount_usd,
                        'discount_amount_sol': discount_amount_usd * self.exchange_rate,
                        'code_used': code.code
                    })
                    return discount_info
                else:
                    discount_info.update({
                        'type': 'error',
                        'description': f"Código inválido: {message}",
                        'discount_percentage': 0,
                        'discount_amount_usd': 0.00,
                        'discount_amount_sol': 0.00,
                        'code_used': clean_code
                    })

            
            except Exception as e:
                discount_info.update({
                    'type': 'error',
                    'description': f"Error al procesar código: {str(e)}",
                    'discount_percentage': 0,
                    'discount_amount_usd': 0.00,
                    'discount_amount_sol': 0.00,
                    'code_used': discount_code.strip() if discount_code else None
                })

        # Evaluar descuentos automáticos si hay cliente y no hay descuento de código válido
        # Aplicar descuentos automáticos si: no hay código, código inválido, o no hay descuento aplicado
        if client and discount_info['type'] in ['none', 'error']:
            from .pricing_models import AutomaticDiscount
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info(f"🤖 EVALUANDO DESCUENTOS AUTOMÁTICOS")
            logger.info(f"👤 Cliente: {client.first_name} {client.last_name or ''} (ID: {client.id})")
            logger.info(f"📅 Fecha de nacimiento: {client.date}")
            logger.info(f"📅 Mes de check-in: {check_in_date.month}")
            logger.info(f"📅 Fecha de check-in: {check_in_date}")
            
            # Buscar descuentos automáticos aplicables al cliente
            automatic_discounts = AutomaticDiscount.objects.filter(is_active=True, deleted=False)
            logger.info(f"📋 Descuentos automáticos disponibles: {automatic_discounts.count()}")
            
            # Evaluar todos los descuentos automáticos aplicables y elegir el mejor
            applicable_discounts = []
            
            for auto_discount in automatic_discounts:
                logger.info(f"🔍 Evaluando: '{auto_discount.name}' - Trigger: '{auto_discount.trigger}'")
                try:
                    applies, message = auto_discount.applies_to_client(client, check_in_date)
                    logger.info(f"✅ Resultado: {applies} - '{message}'")
                    
                    if applies:
                        discount_amount_usd = auto_discount.calculate_discount(subtotal_usd)
                        logger.info(f"💰 Descuento calculado: ${discount_amount_usd} USD ({auto_discount.discount_percentage}%)")
                        applicable_discounts.append({
                            'discount': auto_discount,
                            'message': message,
                            'amount_usd': discount_amount_usd
                        })
                    
                except Exception as e:
                    logger.error(f"❌ Error evaluando descuento {auto_discount.name}: {str(e)}")
            
            # Si hay descuentos aplicables, elegir el que mayor ahorro genere
            if applicable_discounts:
                # Ordenar por monto de descuento (de mayor a menor)
                best_discount = max(applicable_discounts, key=lambda x: x['amount_usd'])
                
                logger.info(f"🏆 MEJOR DESCUENTO: {best_discount['discount'].name} - ${best_discount['amount_usd']} USD")
                
                # Actualizar discount_info con el descuento automático
                discount_info = {
                    'type': 'automatic',
                    'description': best_discount['message'],
                    'discount_percentage': round(float(best_discount['discount'].discount_percentage), 2),
                    'discount_amount_usd': best_discount['amount_usd'],
                    'discount_amount_sol': best_discount['amount_usd'] * self.exchange_rate,
                    'code_used': None
                }
            else:
                logger.info(f"❌ No se encontraron descuentos automáticos aplicables para este cliente")

        return discount_info

    def _get_additional_services(self, property, nights, guests):
        """Obtiene servicios adicionales disponibles"""
        services = AdditionalService.objects.filter(
            is_active=True
        ).filter(
            Q(properties__isnull=True) | Q(properties=property)
        ).distinct()

        service_list = []
        for service in services:
            total_price_usd = service.calculate_price(nights, guests)
            service_list.append({
                'id': service.id,
                'name': service.name,
                'description': service.description,
                'price_usd': round(float(service.price_usd), 2),
                'price_sol': round(float(service.price_usd * self.exchange_rate), 2),
                'service_type': service.service_type,
                'is_per_night': service.is_per_night,
                'is_per_person': service.is_per_person,
                'total_price_usd': round(float(total_price_usd), 2),
                'total_price_sol': round(float(total_price_usd * self.exchange_rate), 2)
            })

        return service_list

    def _get_client_benefits(self, client, property):
        """Obtiene beneficios del cliente"""
        benefits = {
            'points_available': 0,
            'points_value_usd': 0,
            'points_value_sol': 0,
            'referral_code': None,
            'membership_level': 'standard'
        }

        if client:
            # Verificar si el cliente tiene métodos de puntos
            try:
                available_points = client.get_available_points() if hasattr(client, 'get_available_points') else 0
                points_value_usd = available_points * Decimal('0.01')  # 1 punto = $0.01
                referral_code = client.get_referral_code() if hasattr(client, 'get_referral_code') else client.referral_code if hasattr(client, 'referral_code') else None
            except:
                available_points = 0
                points_value_usd = Decimal('0.00')
                referral_code = None

            benefits.update({
                'points_available': available_points,
                'points_value_usd': round(float(points_value_usd), 2),
                'points_value_sol': round(float(points_value_usd * self.exchange_rate), 2),
                'referral_code': referral_code,
                'membership_level': self._get_membership_level(client)
            })

        return benefits

    def _get_membership_level(self, client):
        """Determina el nivel de membresía del cliente"""
        if not client:
            return 'guest'

        reservation_count = Reservation.objects.filter(
            client=client,
            deleted=False,
            status__in=['approved', 'completed']
        ).count()

        if reservation_count >= 10:
            return 'platinum'
        elif reservation_count >= 5:
            return 'gold'
        elif reservation_count >= 2:
            return 'silver'
        else:
            return 'bronze'

    def _get_property_recommendations(self, property, guests, nights, subtotal_usd, available):
        """Genera recomendaciones específicas para la propiedad"""
        recommendations = []

        if not available:
            recommendations.append("Esta propiedad no está disponible para las fechas seleccionadas")

        if property.capacity_max and guests > property.capacity_max:
            recommendations.append(f"Esta propiedad tiene capacidad máxima para {property.capacity_max} personas")

        if nights >= 7:
            recommendations.append("Estancia de 7+ noches - ¡Excelente para relajarse!")

        if subtotal_usd >= 500:
            recommendations.append("Reserva de alto valor - Considere servicios adicionales premium")

        if property.on_temperature_pool_url:
            recommendations.append("Esta propiedad cuenta con piscina temperada disponible")

        return recommendations

    def _get_general_recommendations(self, properties_results, guests, nights):
        """Genera recomendaciones generales"""
        recommendations = []

        available_properties = [p for p in properties_results if p['available']]

        if not available_properties:
            recommendations.append("No hay propiedades disponibles para las fechas seleccionadas")
        elif len(available_properties) < len(properties_results):
            recommendations.append(f"Disponibles {len(available_properties)} de {len(properties_results)} propiedades")

        if nights >= 14:
            recommendations.append("Estancia larga - Considere contactarnos para descuentos especiales")

        if guests >= 8:
            recommendations.append("Grupo grande - Verifique servicios adicionales y políticas de grupo")

        return recommendations

    def _get_client_info(self, client):
        """Información del cliente"""
        if not client:
            return {'status': 'guest', 'message': 'Usuario no registrado'}

        reservation_count = Reservation.objects.filter(
            client=client,
            deleted=False
        ).count()

        return {
            'status': 'registered',
            'name': f"{client.first_name} {client.last_name or ''}".strip(),
            'membership_level': self._get_membership_level(client),
            'total_reservations': reservation_count,
            'points_available': client.get_available_points()
        }

    def _generate_chatbot_messages(self, properties_results, check_in_date, check_out_date, guests, nights, client, property_id):
        """Genera mensajes contextuales para chatbot similares al sistema PHP"""
        from datetime import datetime
        import locale
        
        # Configurar localización en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except:
            try:
                locale.setlocale(locale.LC_TIME, 'es_ES')
            except:
                pass  # Usar configuración por defecto si no está disponible

        # Determinar cantidad de propiedades disponibles
        available_properties = [p for p in properties_results if p['available']]
        estado_disponibilidad = len(available_properties)  # Cantidad de propiedades disponibles

        # Formatear fechas en español
        fecha_inicio_str = check_in_date.strftime("%d de %B de %Y").replace(
            check_in_date.strftime("%B"), self._get_month_name_spanish(check_in_date.month)
        )
        fecha_fin_str = check_out_date.strftime("%d de %B de %Y").replace(
            check_out_date.strftime("%B"), self._get_month_name_spanish(check_out_date.month)
        )

        # Obtener información de descuento de la primera propiedad disponible
        discount_info = None
        if available_properties and 'discount_applied' in available_properties[0]:
            discount_info = available_properties[0]['discount_applied']

        # Generar MESSAGE1 (mensaje de encabezado/contexto)
        message1 = self._generate_message1(
            estado_disponibilidad, fecha_inicio_str, fecha_fin_str, 
            available_properties, guests, nights, client, discount_info,
            check_in_date, check_out_date
        )

        # Generar MESSAGE2 (mensaje de detalles/precios)
        message2 = self._generate_message2(
            estado_disponibilidad, available_properties, properties_results, property_id
        )

        return {
            'estado_disponibilidad': estado_disponibilidad,
            'message1': message1,
            'message2': message2
        }

    def _validate_special_date_requirements(self, property, check_in_date, check_out_date, nights):
        """Valida que las fechas especiales cumplan con los requisitos de noches mínimas y protege rangos de fechas"""
        from datetime import timedelta, date
        from django.db.models import Q
        import logging
        
        logger = logging.getLogger(__name__)
        
        # OPTIMIZACIÓN: Verificar primero si esta propiedad tiene fechas especiales configuradas
        has_special_dates = SpecialDatePricing.objects.filter(
            property=property,
            is_active=True
        ).exists()
        
        if not has_special_dates:
            logger.info(f"Propiedad {property.name} no tiene fechas especiales configuradas - omitiendo validación")
            return
        
        logger.info(f"🔍 Validando protección de fechas especiales para {property.name}")
        logger.info(f"📅 Check-in: {check_in_date}, Check-out: {check_out_date}, Noches: {nights}")
        
        # Obtener todas las fechas especiales de esta propiedad para el año actual y siguiente
        current_year = check_in_date.year
        years_to_check = [current_year, current_year + 1]
        
        for year in years_to_check:
            special_pricings = SpecialDatePricing.objects.filter(
                property=property,
                is_active=True
            )
            
            for special_pricing in special_pricings:
                try:
                    special_date = date(year, special_pricing.month, special_pricing.day)
                    required_nights = special_pricing.minimum_consecutive_nights
                    
                    # Calcular el rango protegido alrededor de la fecha especial
                    # Ejemplo: Si 31/12 requiere 3 noches, proteger del 29/12 al 2/01
                    protected_start = special_date - timedelta(days=required_nights - 1)
                    protected_end = special_date + timedelta(days=required_nights - 1)
                    
                    logger.info(f"🎯 Fecha especial: {special_date.strftime('%d/%m/%Y')} ({special_pricing.description})")
                    logger.info(f"🛡️  Rango protegido: {protected_start.strftime('%d/%m/%Y')} a {protected_end.strftime('%d/%m/%Y')}")
                    logger.info(f"📏 Noches mínimas requeridas: {required_nights}")
                    
                    # Verificar si la reserva propuesta interfiere con el rango protegido
                    reservation_start = check_in_date
                    reservation_end = check_out_date - timedelta(days=1)  # Última noche ocupada
                    
                    # ¿La reserva interfiere con el rango protegido?
                    interferes = not (reservation_end < protected_start or reservation_start > protected_end)
                    
                    if interferes:
                        logger.info(f"⚠️  La reserva interfiere con el rango protegido de {special_pricing.description}")
                        
                        # Verificar si la fecha especial ya está ocupada
                        existing_reservations = Reservation.objects.filter(
                            property=property,
                            deleted=False,
                            status__in=['approved', 'pending', 'incomplete']
                        ).filter(
                            Q(check_in_date__lte=special_date) & Q(check_out_date__gt=special_date)
                        )
                        
                        if existing_reservations.exists():
                            logger.info(f"✅ Fecha especial {special_date.strftime('%d/%m/%Y')} ya está ocupada, permitiendo reserva")
                            continue
                        
                        # La fecha especial está libre, verificar si esta reserva cumple el mínimo
                        if nights < required_nights:
                            error_msg = (
                                f"❌ No se puede realizar esta reserva del {check_in_date.strftime('%d/%m/%Y')} "
                                f"al {check_out_date.strftime('%d/%m/%Y')} ({nights} noche{'s' if nights != 1 else ''}) "
                                f"porque interfiere con la fecha especial {special_date.strftime('%d/%m/%Y')} "
                                f"({special_pricing.description}) que requiere un mínimo de {required_nights} noches consecutivas. "
                                f"\n\n💡 Para incluir esta fecha especial, su reserva debe ser de al menos "
                                f"{required_nights} noches consecutivas que incluyan el {special_date.strftime('%d/%m/%Y')}."
                            )
                            logger.error(f"🚫 VALIDACIÓN FALLIDA: {error_msg}")
                            raise ValueError(error_msg)
                        
                        # Si llega aquí, la reserva incluye la fecha especial y cumple el mínimo
                        # Verificar que efectivamente incluya la fecha especial
                        if not (check_in_date <= special_date < check_out_date):
                            error_msg = (
                                f"❌ No se puede realizar esta reserva del {check_in_date.strftime('%d/%m/%Y')} "
                                f"al {check_out_date.strftime('%d/%m/%Y')} porque interfiere con el rango protegido "
                                f"de la fecha especial {special_date.strftime('%d/%m/%Y')} ({special_pricing.description}) "
                                f"pero no la incluye en la reserva. "
                                f"\n\n💡 Para reservar en estas fechas, debe incluir la fecha especial "
                                f"{special_date.strftime('%d/%m/%Y')} en su estadía de mínimo {required_nights} noches."
                            )
                            logger.error(f"🚫 VALIDACIÓN FALLIDA: {error_msg}")
                            raise ValueError(error_msg)
                        
                        logger.info(f"✅ Reserva válida: incluye fecha especial {special_date.strftime('%d/%m/%Y')} con {nights} noches")
                    
                except ValueError as ve:
                    # Re-lanzar errores de validación
                    raise ve
                except Exception as e:
                    # Fecha inválida (ej: 29/02 en año no bisiesto)
                    logger.warning(f"Fecha especial inválida: {special_pricing.day}/{special_pricing.month}/{year} - {e}")
                    continue
        
        logger.info("✅ Validación de protección de fechas especiales completada exitosamente")

    def _get_month_name_spanish(self, month):
        """Convierte número de mes a nombre en español"""
        months = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
            5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
            9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
        }
        return months.get(month, 'mes')

    def _generate_message1(self, estado_disponibilidad, fecha_inicio_str, fecha_fin_str, available_properties, guests, nights, client, discount_info, check_in_date, check_out_date):
        """Genera mensaje1 según el estado de disponibilidad"""
        from datetime import timedelta
        
        if estado_disponibilidad > 0:
            # Hay propiedades disponibles
            if estado_disponibilidad == 1:
                message1 = f"📅 Disponibilidad del {fecha_inicio_str} al {fecha_fin_str}"
            else:
                message1 = f"📅 Del {fecha_inicio_str} al {fecha_fin_str}\n✨ Encontramos {estado_disponibilidad} casa(s) disponibles"
            
            # Agregar información de descuento si aplica
            if discount_info and discount_info.get('type') not in ['none', 'error']:
                if discount_info['type'] == 'discount_code':
                    percentage = discount_info.get('discount_percentage', 0)
                    if percentage > 0:
                        message1 += f"\n✨ Descuento del {percentage}% aplicado con código '{discount_info.get('code_used', '')}'"
                    else:
                        # Para descuentos de monto fijo
                        amount = discount_info.get('discount_amount_usd', 0)
                        message1 += f"\n✨ Descuento de ${amount} aplicado con código '{discount_info.get('code_used', '')}'"
                elif discount_info['type'] == 'automatic':
                    percentage = discount_info.get('discount_percentage', 0)
                    message1 += f"\n✨ Descuento automático del {percentage}% aplicado por ser cliente registrado"
            
            # Tip para grupos pequeños cuando buscan fin de semana
            if guests < 5:
                # Verificar si alguna de las fechas es viernes o sábado
                current_date = check_in_date
                has_friday_or_saturday = False
                while current_date < check_out_date:
                    if current_date.weekday() in [4, 5]:  # 4=Viernes, 5=Sábado
                        has_friday_or_saturday = True
                        break
                    current_date += timedelta(days=1)
                
                if has_friday_or_saturday:
                    message1 += "\n💡 Tip: Los días de semana son más recomendables para reservas de 5 personas o menos, ya que el costo es menor."
                
        else:
            # Sin disponibilidad
            message1 = f"📅 Disponibilidad del {fecha_inicio_str} al {fecha_fin_str}\n❌ No hay casas disponibles para estas fechas"

        return message1

    def _generate_message2(self, estado_disponibilidad, available_properties, all_properties, property_id):
        """Genera message2 según la disponibilidad específica"""
        
        if estado_disponibilidad == 0:
            # Sin disponibilidad
            return "No hay casas disponibles en las fechas seleccionadas. Te sugerimos revisar otras fechas."
        
        if property_id and available_properties:
            # Casa específica disponible
            property_info = available_properties[0]
            return f"🏠 {property_info['property_name']}: ${property_info['final_price_usd']} Dólares ó S/.{property_info['final_price_sol']} Soles"
        
        if not property_id and available_properties:
            # Mostrar lista de casas disponibles ordenadas por nombre
            # Ordenar propiedades por nombre para mostrar Casa Austin 1, 2, 3, 4
            def sort_key(prop):
                name = prop['property_name'].lower()
                # Extraer el número al final del nombre si existe
                import re
                match = re.search(r'(\d+)$', name)
                if match:
                    # Si tiene número al final, usar ese número para ordenar
                    base_name = re.sub(r'\s*\d+$', '', name)
                    number = int(match.group(1))
                    return (base_name, number)
                else:
                    # Si no tiene número, ordenar alfabéticamente
                    return (name, 0)
            
            sorted_properties = sorted(available_properties, key=sort_key)
            casas_disponibles = []
            for prop in sorted_properties:
                casas_disponibles.append(
                    f"🏠 {prop['property_name']}: ${prop['final_price_usd']} USD ó S/.{prop['final_price_sol']} SOL"
                )
            return "\n".join(casas_disponibles)
        
        return "Información de disponibilidad no disponible."