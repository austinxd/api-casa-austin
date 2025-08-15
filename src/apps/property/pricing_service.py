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

        # Información general
        general_info = {
            'check_in_date': check_in_date,
            'check_out_date': check_out_date,
            'guests': guests,
            'total_nights': nights,
            'exchange_rate': self.exchange_rate,
            'properties': results,
            'general_recommendations': self._get_general_recommendations(results, guests, nights),
            'client_info': self._get_client_info(client)
        }

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
            property, subtotal_usd, Decimal(0), nights, guests, discount_code # Corregido para pasar property y subtotal_usd, subtotal_sol, nights, guests, discount_code
        )

        final_price_usd = subtotal_usd - discount_applied['discount_amount_usd']
        final_price_sol = (subtotal_usd * self.exchange_rate) - discount_applied['discount_amount_sol']

        # Calcular precio total que incluye todo (base + extras + aplicar descuentos)
        total_price_usd = final_price_usd
        total_price_sol = final_price_sol


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

        return {
            'property_id': property.id,
            'property_name': property.name,
            'property_slug': property.slug,
            'base_price_usd': float(base_total_usd),
            'base_price_sol': float(base_price_sol),
            'extra_person_price_per_night_usd': float(extra_person_price_usd),
            'extra_person_price_per_night_sol': float(extra_person_price_sol),
            'extra_person_total_usd': float(extra_person_total_usd),
            'extra_person_total_sol': float(extra_person_total_sol),
            'total_nights': nights,
            'total_guests': guests,
            'extra_guests': extra_guests,
            'subtotal_usd': float(subtotal_usd),
            'subtotal_sol': float(subtotal_sol),
            'discount_applied': discount_applied,
            'final_price_usd': float(final_price_usd),
            'final_price_sol': float(final_price_sol),
            'total_price_usd': float(total_price_usd),
            'total_price_sol': float(total_price_sol),
            'available': available,
            'availability_message': availability_message,
            'additional_services': additional_services,
            'cancellation_policy': cancellation_policy,
            'client_benefits': client_benefits,
            'recommendations': recommendations
        }

    def _check_availability(self, property, check_in_date, check_out_date):
        """Verifica disponibilidad de la propiedad"""
        conflicting_reservations = Reservation.objects.filter(
            property=property,
            deleted=False,
            status__in=['approved', 'pending']
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

    def _apply_discounts(self, property, subtotal_usd, subtotal_sol, nights, guests, discount_code):
        """Aplica descuentos automáticos o códigos de descuento"""
        discount_info = {
            'type': 'none',
            'description': 'Sin descuento',
            'discount_percentage': 0,
            'discount_amount_usd': Decimal('0.00'),
            'discount_amount_sol': Decimal('0.00'),
            'code_used': None
        }

        # Si hay código de descuento, verificar y aplicar
        if discount_code:
            try:
                code = DiscountCode.objects.get(code=discount_code.upper(), is_active=True)
                is_valid, message = code.is_valid(property.id, subtotal_usd) # Se necesita el id de la propiedad para validar el código de descuento

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
                    discount_info['description'] = f"Código inválido: {message}"

            except DiscountCode.DoesNotExist:
                discount_info['description'] = "Código de descuento no encontrado"

        # Si no hay código válido, verificar descuentos automáticos
        if client:
            from .pricing_models import AutomaticDiscount
            
            # Buscar descuentos automáticos aplicables al cliente
            automatic_discounts = AutomaticDiscount.objects.filter(is_active=True)
            
            for auto_discount in automatic_discounts:
                applies, message = auto_discount.applies_to_client(client)
                
                if applies:
                    discount_amount_usd = auto_discount.calculate_discount(subtotal_usd)
                    discount_info.update({
                        'type': 'automatic',
                        'description': message,
                        'discount_percentage': float(auto_discount.discount_percentage),
                        'discount_amount_usd': discount_amount_usd,
                        'discount_amount_sol': discount_amount_usd * self.exchange_rate,
                        'code_used': None
                    })
                    break  # Aplicar solo el primer descuento automático que califique

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
                'price_usd': float(service.price_usd),
                'price_sol': float(service.price_usd * self.exchange_rate),
                'service_type': service.service_type,
                'is_per_night': service.is_per_night,
                'is_per_person': service.is_per_person,
                'total_price_usd': float(total_price_usd),
                'total_price_sol': float(total_price_usd * self.exchange_rate)
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
                'points_value_usd': float(points_value_usd),
                'points_value_sol': float(points_value_usd * self.exchange_rate),
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