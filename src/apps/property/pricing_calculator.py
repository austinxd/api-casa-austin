
from decimal import Decimal
from datetime import date, timedelta
from django.db.models import Q
from .models import Property
from .pricing_models import SeasonPricing, SpecialDatePricing, ExchangeRate


class PricingCalculator:
    """Calculadora de precios para propiedades"""
    
    def __init__(self, property_instance):
        self.property = property_instance
    
    def get_price_for_date(self, check_date, guests=1):
        """
        Obtiene el precio para una fecha específica
        Prioridad: 1) Fechas especiales, 2) Precios de temporada, 3) Precio base
        """
        # 1. Verificar si hay precio especial para esta fecha
        special_price = SpecialDatePricing.objects.filter(
            property=self.property,
            date=check_date,
            is_active=True
        ).first()
        
        if special_price:
            return special_price.calculate_total_price(guests)
        
        # 2. Buscar precio de temporada
        season_price = SeasonPricing.objects.filter(
            property=self.property,
            start_date__lte=check_date,
            end_date__gte=check_date,
            is_active=True
        ).first()
        
        if season_price:
            return season_price.calculate_total_price_for_date(check_date, guests)
        
        # 3. Usar precio base de la propiedad si está disponible
        if self.property.precio_desde:
            base_price = self.property.precio_desde
            if guests > 1 and self.property.precio_extra_persona:
                additional_guests = guests - 1
                additional_cost = self.property.precio_extra_persona * additional_guests
                return base_price + additional_cost
            return base_price
        
        # 4. Precio por defecto si no hay nada configurado
        return Decimal('100.00')
    
    def calculate_stay_total(self, check_in, check_out, guests=1):
        """
        Calcula el precio total para una estadía
        Args:
            check_in (date): Fecha de entrada
            check_out (date): Fecha de salida
            guests (int): Número de huéspedes
        Returns:
            dict: Información detallada del cálculo de precios
        """
        if check_in >= check_out:
            raise ValueError("La fecha de entrada debe ser anterior a la fecha de salida")
        
        current_date = check_in
        total_usd = Decimal('0.00')
        nights = 0
        pricing_breakdown = []
        
        while current_date < check_out:
            night_price = self.get_price_for_date(current_date, guests)
            total_usd += night_price
            nights += 1
            
            # Información detallada de la noche
            pricing_breakdown.append({
                'date': current_date,
                'price_usd': night_price,
                'day_type': self._get_day_type(current_date),
                'season_type': self._get_season_type(current_date)
            })
            
            current_date += timedelta(days=1)
        
        # Convertir a soles usando tipo de cambio actual
        exchange_rate = ExchangeRate.get_current_rate()
        total_sol = total_usd * exchange_rate
        
        return {
            'check_in': check_in,
            'check_out': check_out,
            'nights': nights,
            'guests': guests,
            'total_usd': total_usd,
            'total_sol': total_sol,
            'exchange_rate': exchange_rate,
            'price_per_night_avg_usd': total_usd / nights if nights > 0 else Decimal('0.00'),
            'pricing_breakdown': pricing_breakdown,
            'base_persons': 1,
            'additional_persons': max(0, guests - 1),
            'extra_person_cost_per_night': self.property.precio_extra_persona or Decimal('0.00')
        }
    
    def _get_day_type(self, check_date):
        """Determina el tipo de día (fin de semana o día de semana)"""
        weekday = check_date.weekday()
        if weekday >= 4:  # Viernes, Sábado, Domingo
            return 'weekend'
        return 'weekday'
    
    def _get_season_type(self, check_date):
        """Determina el tipo de temporada para una fecha"""
        season = SeasonPricing.objects.filter(
            property=self.property,
            start_date__lte=check_date,
            end_date__gte=check_date,
            is_active=True
        ).first()
        
        if season:
            return season.get_season_type_display()
        
        return 'Sin temporada configurada'
    
    def get_pricing_summary(self):
        """
        Obtiene un resumen de la configuración de precios de la propiedad
        """
        # Precios de temporada
        season_prices = SeasonPricing.objects.filter(
            property=self.property,
            is_active=True
        ).order_by('season_type', 'start_date')
        
        # Fechas especiales
        special_dates = SpecialDatePricing.objects.filter(
            property=self.property,
            is_active=True
        ).order_by('date')
        
        return {
            'property_name': self.property.name,
            'base_price': self.property.precio_desde,
            'extra_person_price': self.property.precio_extra_persona,
            'max_capacity': self.property.capacity_max,
            'season_prices': [
                {
                    'season': sp.get_season_type_display(),
                    'period': f"{sp.start_date} - {sp.end_date}",
                    'weekday_price': sp.weekday_price_usd,
                    'weekend_price': sp.weekend_price_usd
                }
                for sp in season_prices
            ],
            'special_dates': [
                {
                    'date': sd.date,
                    'name': sd.name,
                    'price': sd.price_usd
                }
                for sd in special_dates
            ],
            'current_exchange_rate': ExchangeRate.get_current_rate()
        }
