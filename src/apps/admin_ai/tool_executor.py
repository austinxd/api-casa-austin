"""
Ejecutor de herramientas para el asistente IA financiero.
Cada método consulta datos reales de la base de datos.
"""
import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import models as db_models
from django.db.models import Sum, Avg, Count, Q, F, Min, Max
from django.utils import timezone

logger = logging.getLogger(__name__)


class AdminToolExecutor:
    """Ejecuta las herramientas financieras invocadas por la IA"""

    def execute(self, tool_name, arguments):
        """Ejecuta una herramienta y retorna el resultado como string"""
        tool_map = {
            'get_revenue_summary': self._get_revenue_summary,
            'get_occupancy_rates': self._get_occupancy_rates,
            'get_reservation_stats': self._get_reservation_stats,
            'get_pricing_overview': self._get_pricing_overview,
            'get_property_details': self._get_property_details,
            'get_financial_projections': self._get_financial_projections,
            'get_client_analytics': self._get_client_analytics,
            'get_chatbot_performance': self._get_chatbot_performance,
            'get_nightly_rate_analysis': self._get_nightly_rate_analysis,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return f"Error: herramienta '{tool_name}' no encontrada"

        try:
            return handler(**arguments)
        except Exception as e:
            logger.error(f"Error ejecutando {tool_name}: {e}", exc_info=True)
            return f"Error al ejecutar {tool_name}: {str(e)}"

    def _parse_dates(self, date_from=None, date_to=None, default_days=30):
        """Parsea fechas con valores por defecto"""
        today = date.today()
        if date_to:
            try:
                dt_to = date.fromisoformat(date_to)
            except ValueError:
                dt_to = today
        else:
            dt_to = today

        if date_from:
            try:
                dt_from = date.fromisoformat(date_from)
            except ValueError:
                dt_from = dt_to - timedelta(days=default_days)
        else:
            dt_from = dt_to - timedelta(days=default_days)

        return dt_from, dt_to

    def _get_revenue_summary(self, date_from=None, date_to=None, property_name=None):
        from apps.reservation.models import Reservation
        from apps.property.models import Property

        dt_from, dt_to = self._parse_dates(date_from, date_to)

        qs = Reservation.objects.filter(
            check_in_date__gte=dt_from,
            check_in_date__lte=dt_to,
            status='approved',
            deleted=False,
        )
        if property_name:
            qs = qs.filter(property__name__icontains=property_name)

        # Totales generales
        totals = qs.aggregate(
            total_sol=Sum('price_sol'),
            total_usd=Sum('price_usd'),
            avg_sol=Avg('price_sol'),
            avg_usd=Avg('price_usd'),
            count=Count('id'),
        )

        total_sol = float(totals['total_sol'] or 0)
        total_usd = float(totals['total_usd'] or 0)
        avg_sol = float(totals['avg_sol'] or 0)
        avg_usd = float(totals['avg_usd'] or 0)
        count = totals['count'] or 0

        # Total de noches
        total_nights = 0
        for r in qs.only('check_in_date', 'check_out_date'):
            nights = (r.check_out_date - r.check_in_date).days
            if nights > 0:
                total_nights += nights

        # Desglose por propiedad
        by_property = (
            qs.values('property__name')
            .annotate(
                revenue_sol=Sum('price_sol'),
                revenue_usd=Sum('price_usd'),
                reservations=Count('id'),
            )
            .order_by('-revenue_sol')
        )

        days_in_period = (dt_to - dt_from).days + 1
        properties = Property.objects.filter(deleted=False)
        total_available_nights = properties.count() * days_in_period
        revpar = total_sol / total_available_nights if total_available_nights > 0 else 0

        result = {
            'periodo': f"{dt_from} a {dt_to} ({days_in_period} días)",
            'total_reservas_aprobadas': count,
            'ingresos_soles': round(total_sol, 2),
            'ingresos_dolares': round(total_usd, 2),
            'promedio_por_reserva_sol': round(avg_sol, 2),
            'promedio_por_reserva_usd': round(avg_usd, 2),
            'total_noches_vendidas': total_nights,
            'ingreso_por_noche_sol': round(total_sol / total_nights, 2) if total_nights else 0,
            'RevPAR_sol': round(revpar, 2),
            'desglose_por_propiedad': [
                {
                    'propiedad': p['property__name'],
                    'ingresos_sol': float(p['revenue_sol'] or 0),
                    'ingresos_usd': float(p['revenue_usd'] or 0),
                    'reservas': p['reservations'],
                }
                for p in by_property
            ],
        }

        # Si no hay datos, agregar contexto útil
        if count == 0:
            all_props = list(Property.objects.filter(deleted=False).values_list('name', flat=True))
            all_reservations = Reservation.objects.filter(status='approved', deleted=False)
            date_range = all_reservations.aggregate(
                min_date=Min('check_in_date'),
                max_date=Max('check_in_date'),
            )
            result['nota'] = 'No se encontraron reservas aprobadas en este período.'
            result['propiedades_existentes'] = all_props
            result['rango_datos_disponibles'] = {
                'desde': str(date_range['min_date']) if date_range['min_date'] else 'sin datos',
                'hasta': str(date_range['max_date']) if date_range['max_date'] else 'sin datos',
            }
            result['total_reservas_historicas'] = all_reservations.count()

        return json.dumps(result, ensure_ascii=False)

    def _get_occupancy_rates(self, date_from=None, date_to=None):
        from apps.reservation.models import Reservation
        from apps.property.models import Property

        dt_from, dt_to = self._parse_dates(date_from, date_to)
        days_in_period = (dt_to - dt_from).days + 1

        properties = Property.objects.filter(deleted=False)
        occupancy = []

        for prop in properties:
            reservations = Reservation.objects.filter(
                property=prop,
                status='approved',
                deleted=False,
                check_in_date__lte=dt_to,
                check_out_date__gte=dt_from,
            )
            occupied_nights = 0
            for r in reservations:
                start = max(r.check_in_date, dt_from)
                end = min(r.check_out_date, dt_to)
                nights = (end - start).days
                if nights > 0:
                    occupied_nights += nights

            rate = (occupied_nights / days_in_period * 100) if days_in_period > 0 else 0
            occupancy.append({
                'propiedad': prop.name,
                'noches_ocupadas': occupied_nights,
                'noches_disponibles': days_in_period,
                'tasa_ocupacion': round(rate, 1),
            })

        occupancy.sort(key=lambda x: x['tasa_ocupacion'], reverse=True)

        avg_rate = sum(o['tasa_ocupacion'] for o in occupancy) / len(occupancy) if occupancy else 0

        result = {
            'periodo': f"{dt_from} a {dt_to} ({days_in_period} días)",
            'ocupacion_promedio': round(avg_rate, 1),
            'por_propiedad': occupancy,
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_reservation_stats(self, date_from=None, date_to=None, property_name=None):
        from apps.reservation.models import Reservation

        dt_from, dt_to = self._parse_dates(date_from, date_to)

        qs = Reservation.objects.filter(
            check_in_date__gte=dt_from,
            check_in_date__lte=dt_to,
            deleted=False,
        )
        if property_name:
            qs = qs.filter(property__name__icontains=property_name)

        # Por estado
        by_status = dict(
            qs.values_list('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        )

        # Estancia promedio (solo aprobadas)
        approved = qs.filter(status='approved')
        stays = []
        for r in approved.only('check_in_date', 'check_out_date'):
            nights = (r.check_out_date - r.check_in_date).days
            if nights > 0:
                stays.append(nights)
        avg_stay = sum(stays) / len(stays) if stays else 0

        # Por origen
        by_origin = dict(
            qs.values_list('origin')
            .annotate(count=Count('id'))
            .values_list('origin', 'count')
        )

        origin_labels = {
            'air': 'Airbnb',
            'aus': 'Austin (directo)',
            'man': 'Mantenimiento',
            'client': 'Cliente Web',
        }

        # Por propiedad
        by_property = list(
            qs.filter(status='approved')
            .values('property__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        result = {
            'periodo': f"{dt_from} a {dt_to}",
            'total_reservas': qs.count(),
            'por_estado': {
                k: v for k, v in by_status.items()
            },
            'estancia_promedio_noches': round(avg_stay, 1),
            'por_origen': {
                origin_labels.get(k, k): v for k, v in by_origin.items()
            },
            'aprobadas_por_propiedad': [
                {'propiedad': p['property__name'], 'reservas': p['count']}
                for p in by_property
            ],
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_pricing_overview(self, property_name=None):
        from apps.property.models import Property
        from apps.property.pricing_models import PropertyPricing, SeasonPricing, SpecialDatePricing

        props = Property.objects.filter(deleted=False)
        if property_name:
            props = props.filter(name__icontains=property_name)

        pricing_data = []
        for prop in props:
            entry = {'propiedad': prop.name, 'capacidad_max': prop.capacity_max}
            try:
                pp = PropertyPricing.objects.get(property=prop)
                entry['precios_base_usd'] = {
                    'dia_semana_temporada_baja': float(pp.weekday_low_season_usd),
                    'fin_semana_temporada_baja': float(pp.weekend_low_season_usd),
                    'dia_semana_temporada_alta': float(pp.weekday_high_season_usd),
                    'fin_semana_temporada_alta': float(pp.weekend_high_season_usd),
                }
            except PropertyPricing.DoesNotExist:
                entry['precios_base_usd'] = 'No configurado'

            # Fechas especiales
            specials = SpecialDatePricing.objects.filter(property=prop, is_active=True)
            if specials.exists():
                entry['fechas_especiales'] = [
                    {
                        'descripcion': s.description,
                        'fecha': f"{s.day}/{s.month}",
                        'precio_usd': float(s.price_usd),
                        'minimo_noches': s.minimum_consecutive_nights,
                    }
                    for s in specials
                ]

            if prop.precio_extra_persona:
                entry['precio_extra_persona_usd'] = float(prop.precio_extra_persona)

            pricing_data.append(entry)

        # Temporadas globales
        seasons = SeasonPricing.objects.filter(is_active=True)
        seasons_data = [
            {
                'nombre': s.name,
                'tipo': s.get_season_type_display(),
                'periodo': f"{s.start_day}/{s.start_month} - {s.end_day}/{s.end_month}",
            }
            for s in seasons
        ]

        result = {
            'propiedades': pricing_data,
            'temporadas_globales': seasons_data,
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_property_details(self, property_name=None):
        from apps.property.models import Property

        props = Property.objects.filter(deleted=False)
        if property_name:
            props = props.filter(name__icontains=property_name)

        details = []
        for prop in props:
            entry = {
                'nombre': prop.name,
                'ubicacion': prop.location,
                'capacidad_max': prop.capacity_max,
                'dormitorios': prop.dormitorios,
                'banos': prop.banos,
                'hora_ingreso': str(prop.hora_ingreso) if prop.hora_ingreso else None,
                'hora_salida': str(prop.hora_salida) if prop.hora_salida else None,
                'caracteristicas': prop.caracteristicas,
            }
            if prop.detalle_dormitorios:
                entry['detalle_dormitorios'] = prop.detalle_dormitorios
            details.append(entry)

        return json.dumps({'propiedades': details}, ensure_ascii=False)

    def _get_financial_projections(self, months_back=3, months_forward=1):
        from apps.reservation.models import Reservation

        today = date.today()

        # Datos históricos por mes
        monthly_data = []
        for i in range(months_back, 0, -1):
            month_start = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

            qs = Reservation.objects.filter(
                check_in_date__gte=month_start,
                check_in_date__lte=month_end,
                status='approved',
                deleted=False,
            )
            total = qs.aggregate(sol=Sum('price_sol'), usd=Sum('price_usd'), count=Count('id'))
            monthly_data.append({
                'mes': month_start.strftime('%Y-%m'),
                'ingresos_sol': float(total['sol'] or 0),
                'ingresos_usd': float(total['usd'] or 0),
                'reservas': total['count'] or 0,
            })

        # Crecimiento promedio mensual
        revenues = [m['ingresos_sol'] for m in monthly_data if m['ingresos_sol'] > 0]
        if len(revenues) >= 2:
            growth_rates = []
            for i in range(1, len(revenues)):
                if revenues[i - 1] > 0:
                    growth_rates.append((revenues[i] - revenues[i - 1]) / revenues[i - 1])
            avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0
        else:
            avg_growth = 0

        avg_monthly = sum(revenues) / len(revenues) if revenues else 0

        # Reservas futuras confirmadas
        future_qs = Reservation.objects.filter(
            check_in_date__gt=today,
            check_in_date__lte=today + timedelta(days=30 * months_forward),
            status='approved',
            deleted=False,
        )
        future_totals = future_qs.aggregate(sol=Sum('price_sol'), count=Count('id'))

        result = {
            'historico_mensual': monthly_data,
            'promedio_mensual_sol': round(avg_monthly, 2),
            'crecimiento_promedio_mensual': f"{round(avg_growth * 100, 1)}%",
            'proyeccion': {
                'meses_adelante': months_forward,
                'estimado_sol': round(avg_monthly * (1 + avg_growth) * months_forward, 2),
                'reservas_ya_confirmadas': future_totals['count'] or 0,
                'ingresos_ya_confirmados_sol': float(future_totals['sol'] or 0),
            },
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_client_analytics(self, date_from=None, date_to=None, top_n=10):
        from apps.reservation.models import Reservation
        from apps.clients.models import Clients

        dt_from, dt_to = self._parse_dates(date_from, date_to, default_days=90)

        approved = Reservation.objects.filter(
            check_in_date__gte=dt_from,
            check_in_date__lte=dt_to,
            status='approved',
            deleted=False,
            client__isnull=False,
        )

        # Top clientes por gasto
        top_clients = (
            approved
            .values('client__first_name', 'client__last_name', 'client__tel_number')
            .annotate(
                total_sol=Sum('price_sol'),
                total_reservas=Count('id'),
            )
            .order_by('-total_sol')[:top_n]
        )

        # Nuevos vs recurrentes
        unique_clients = approved.values('client').distinct().count()
        clients_with_history = (
            approved.values('client')
            .annotate(res_count=Count('id'))
            .filter(res_count__gt=1)
            .count()
        )

        # Total clientes en sistema
        total_clients = Clients.objects.filter(deleted=False).count()

        result = {
            'periodo': f"{dt_from} a {dt_to}",
            'clientes_unicos_con_reserva': unique_clients,
            'clientes_recurrentes': clients_with_history,
            'total_clientes_en_sistema': total_clients,
            'top_clientes': [
                {
                    'nombre': f"{c['client__first_name']} {c['client__last_name'] or ''}".strip(),
                    'telefono': c['client__tel_number'],
                    'gasto_total_sol': float(c['total_sol'] or 0),
                    'reservas': c['total_reservas'],
                }
                for c in top_clients
            ],
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_chatbot_performance(self, date_from=None, date_to=None):
        from apps.chatbot.models import ChatAnalytics

        dt_from, dt_to = self._parse_dates(date_from, date_to)

        analytics = ChatAnalytics.objects.filter(
            date__gte=dt_from,
            date__lte=dt_to,
        )

        totals = analytics.aggregate(
            sessions=Sum('total_sessions'),
            new_sessions=Sum('new_sessions'),
            msgs_in=Sum('total_messages_in'),
            msgs_ai=Sum('total_messages_out_ai'),
            msgs_human=Sum('total_messages_out_human'),
            escalations=Sum('escalations'),
            tokens_in=Sum('total_tokens_input'),
            tokens_out=Sum('total_tokens_output'),
            cost=Sum('estimated_cost_usd'),
            reservations=Sum('reservations_created'),
            leads=Sum('bot_leads'),
            conversions=Sum('bot_conversions'),
        )

        result = {
            'periodo': f"{dt_from} a {dt_to}",
            'total_sesiones': totals['sessions'] or 0,
            'nuevas_sesiones': totals['new_sessions'] or 0,
            'mensajes_entrantes': totals['msgs_in'] or 0,
            'mensajes_ia': totals['msgs_ai'] or 0,
            'mensajes_humanos': totals['msgs_human'] or 0,
            'escalaciones': totals['escalations'] or 0,
            'reservas_creadas': totals['reservations'] or 0,
            'leads_generados': totals['leads'] or 0,
            'conversiones': totals['conversions'] or 0,
            'costo_estimado_usd': float(totals['cost'] or 0),
            'tokens_usados': (totals['tokens_in'] or 0) + (totals['tokens_out'] or 0),
        }
        return json.dumps(result, ensure_ascii=False)

    def _get_nightly_rate_analysis(self, months_back=6, months_forward=2, property_name=None):
        from apps.reservation.models import Reservation
        from apps.property.models import Property
        from apps.property.pricing_models import PropertyPricing, SeasonPricing, SpecialDatePricing
        from calendar import monthrange

        today = date.today()

        properties = Property.objects.filter(deleted=False)
        if property_name:
            properties = properties.filter(name__icontains=property_name)

        # Generar lista de meses a analizar
        months = []
        start_month = today.month - months_back
        start_year = today.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1

        current = date(start_year, start_month, 1)
        end_month_offset = months_forward
        end_date = today.replace(day=1)
        for _ in range(end_month_offset):
            if end_date.month == 12:
                end_date = end_date.replace(year=end_date.year + 1, month=1)
            else:
                end_date = end_date.replace(month=end_date.month + 1)

        while current <= end_date:
            months.append(current)
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        result_by_property = []

        for prop in properties:
            # Obtener tarifas configuradas
            try:
                pricing = PropertyPricing.objects.get(property=prop)
                has_pricing = True
            except PropertyPricing.DoesNotExist:
                has_pricing = False

            prop_months = []
            for month_start in months:
                days_in_month = monthrange(month_start.year, month_start.month)[1]
                month_end = date(month_start.year, month_start.month, days_in_month)

                # Contar noches weekday y weekend en el mes
                weekday_nights = 0
                weekend_nights = 0
                d = month_start
                while d <= month_end:
                    # Vie=4, Sáb=5 son weekend
                    if d.weekday() in (4, 5):
                        weekend_nights += 1
                    else:
                        weekday_nights += 1
                    d += timedelta(days=1)

                # Determinar temporada predominante del mes
                if has_pricing:
                    mid_month = date(month_start.year, month_start.month, 15)
                    is_high = SeasonPricing.is_high_season(mid_month)
                    season_name = 'alta' if is_high else 'baja'
                    if is_high:
                        rate_weekday = float(pricing.weekday_high_season_usd)
                        rate_weekend = float(pricing.weekend_high_season_usd)
                    else:
                        rate_weekday = float(pricing.weekday_low_season_usd)
                        rate_weekend = float(pricing.weekend_low_season_usd)

                    # Revisar si hay fechas especiales en el mes
                    specials = SpecialDatePricing.objects.filter(
                        property=prop,
                        is_active=True,
                        month=month_start.month,
                    )
                    special_dates_info = [
                        {
                            'dia': s.day,
                            'descripcion': s.description,
                            'precio_usd': float(s.price_usd),
                            'minimo_noches': s.minimum_consecutive_nights,
                        }
                        for s in specials
                    ]
                else:
                    season_name = 'sin configurar'
                    rate_weekday = 0
                    rate_weekend = 0
                    special_dates_info = []

                # Reservas reales de este mes para esta propiedad
                reservations = Reservation.objects.filter(
                    property=prop,
                    status='approved',
                    deleted=False,
                    check_in_date__lte=month_end,
                    check_out_date__gte=month_start,
                )

                occupied_weekday = 0
                occupied_weekend = 0
                month_revenue_sol = Decimal('0')
                month_revenue_usd = Decimal('0')
                reservation_count = 0

                for r in reservations:
                    # Solo contar noches dentro de este mes
                    r_start = max(r.check_in_date, month_start)
                    r_end = min(r.check_out_date, month_end)
                    total_r_nights = (r.check_out_date - r.check_in_date).days
                    nights_in_month = (r_end - r_start).days
                    if nights_in_month <= 0:
                        continue

                    reservation_count += 1

                    d = r_start
                    while d < r_end:
                        if d.weekday() in (4, 5):
                            occupied_weekend += 1
                        else:
                            occupied_weekday += 1
                        d += timedelta(days=1)

                    # Prorratear ingreso si la reserva cruza meses
                    if total_r_nights > 0:
                        ratio = Decimal(str(nights_in_month)) / Decimal(str(total_r_nights))
                        month_revenue_sol += (r.price_sol or Decimal('0')) * ratio
                        month_revenue_usd += (r.price_usd or Decimal('0')) * ratio

                total_occupied = occupied_weekday + occupied_weekend
                total_available = weekday_nights + weekend_nights
                occupancy_pct = round(total_occupied / total_available * 100, 1) if total_available > 0 else 0

                month_data = {
                    'mes': month_start.strftime('%Y-%m'),
                    'temporada': season_name,
                    'tarifa_weekday_usd': rate_weekday,
                    'tarifa_weekend_usd': rate_weekend,
                    'noches_weekday_disponibles': weekday_nights,
                    'noches_weekend_disponibles': weekend_nights,
                    'noches_weekday_ocupadas': occupied_weekday,
                    'noches_weekend_ocupadas': occupied_weekend,
                    'ocupacion_weekday_pct': round(occupied_weekday / weekday_nights * 100, 1) if weekday_nights > 0 else 0,
                    'ocupacion_weekend_pct': round(occupied_weekend / weekend_nights * 100, 1) if weekend_nights > 0 else 0,
                    'ocupacion_total_pct': occupancy_pct,
                    'reservas': reservation_count,
                    'ingreso_real_sol': round(float(month_revenue_sol), 2),
                    'ingreso_real_usd': round(float(month_revenue_usd), 2),
                    'precio_promedio_noche_sol': round(float(month_revenue_sol) / total_occupied, 2) if total_occupied > 0 else 0,
                    'precio_promedio_noche_usd': round(float(month_revenue_usd) / total_occupied, 2) if total_occupied > 0 else 0,
                }
                if special_dates_info:
                    month_data['fechas_especiales'] = special_dates_info

                # Ingreso potencial (si estuviera 100% ocupado a tarifas configuradas)
                if has_pricing:
                    potential = (rate_weekday * weekday_nights) + (rate_weekend * weekend_nights)
                    month_data['ingreso_potencial_usd'] = round(potential, 2)
                    month_data['captacion_pct'] = round(float(month_revenue_usd) / potential * 100, 1) if potential > 0 else 0

                prop_months.append(month_data)

            # Precio extra por persona
            extra_persona = float(prop.precio_extra_persona) if prop.precio_extra_persona else 0

            result_by_property.append({
                'propiedad': prop.name,
                'capacidad_max': prop.capacity_max,
                'precio_extra_persona_usd': extra_persona,
                'meses': prop_months,
            })

        result = {
            'periodo_analizado': f"{months[0].strftime('%Y-%m')} a {months[-1].strftime('%Y-%m')}" if months else 'sin datos',
            'nota': 'Tarifas weekday=Dom-Jue, weekend=Vie-Sáb. Ingresos prorrateados para reservas que cruzan meses.',
            'propiedades': result_by_property,
        }
        return json.dumps(result, ensure_ascii=False)
