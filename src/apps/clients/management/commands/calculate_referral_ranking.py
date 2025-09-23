from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Count
from django.db import transaction
import calendar
import logging

from apps.clients.models import Clients, ReferralRanking
from apps.reservation.models import Reservation

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Calcula el ranking mensual de referidos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='Año para calcular el ranking (por defecto: año actual)'
        )
        parser.add_argument(
            '--month',
            type=int,
            help='Mes para calcular el ranking (por defecto: mes anterior)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar recálculo incluso si ya existe'
        )

    def handle(self, *args, **options):
        # Determinar período
        now = timezone.now()
        target_year = options['year'] or now.year
        
        # Por defecto usar mes anterior
        if options['month']:
            target_month = options['month']
        else:
            # Mes anterior
            if now.month == 1:
                target_month = 12
                target_year = now.year - 1
            else:
                target_month = now.month - 1

        force_recalc = options['force']

        self.stdout.write(f"Calculando ranking de referidos para {target_month}/{target_year}")

        try:
            with transaction.atomic():
                self.calculate_monthly_ranking(target_year, target_month, force_recalc)
                
            self.stdout.write(
                self.style.SUCCESS(f"✅ Ranking calculado exitosamente para {target_month}/{target_year}")
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error calculando ranking: {str(e)}")
            )
            logger.error(f"Error in calculate_referral_ranking: {str(e)}")

    def calculate_monthly_ranking(self, year, month, force_recalc=False):
        """Calcula el ranking mensual de referidos"""
        from datetime import date
        
        # Verificar si ya existe el ranking para este mes
        existing_rankings = ReferralRanking.objects.filter(
            year=year,
            month=month,
            deleted=False
        )
        
        if existing_rankings.exists() and not force_recalc:
            self.stdout.write(
                self.style.WARNING(f"⚠️ Ya existe ranking para {month}/{year}. Usa --force para recalcular.")
            )
            return

        # Si forzamos recálculo, borrar existentes
        if force_recalc:
            existing_rankings.update(deleted=True)
            self.stdout.write(f"🗑️ Eliminando ranking existente para {month}/{year}")

        # Calcular rango de fechas del mes
        start_date = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = date(year, month, last_day)

        self.stdout.write(f"📅 Período: {start_date} a {end_date}")

        # Obtener todos los clientes con referidos
        clients_with_referrals = Clients.objects.filter(
            referrals__isnull=False,  # Clientes que han hecho referidos
            deleted=False
        ).distinct()

        rankings_data = []

        for client in clients_with_referrals:
            # Obtener estadísticas del mes
            stats = client.get_referral_stats(year, month)
            
            # Solo incluir clientes con al menos una reserva de referido
            if stats['referral_reservations_count'] > 0:
                rankings_data.append({
                    'client': client,
                    'stats': stats
                })

        # Ordenar por cantidad de reservas de referidos (descendente)
        rankings_data.sort(
            key=lambda x: (
                x['stats']['referral_reservations_count'],
                x['stats']['total_referral_revenue']
            ), 
            reverse=True
        )

        # Crear registros de ranking
        created_count = 0
        for position, data in enumerate(rankings_data, 1):
            client = data['client']
            stats = data['stats']
            
            ReferralRanking.objects.create(
                client=client,
                year=year,
                month=month,
                referral_reservations_count=stats['referral_reservations_count'],
                total_referral_revenue=stats['total_referral_revenue'],
                referrals_made_count=stats['referrals_made_count'],
                points_earned=stats['points_earned'],
                position=position
            )
            
            created_count += 1

        self.stdout.write(f"📊 Creados {created_count} registros de ranking")
        
        # Mostrar top 5
        top_rankings = ReferralRanking.objects.filter(
            year=year,
            month=month,
            deleted=False
        ).select_related('client').order_by('position')[:5]

        if top_rankings:
            self.stdout.write("\n🏆 TOP 5 DEL MES:")
            for ranking in top_rankings:
                self.stdout.write(
                    f"  {ranking.position}° {ranking.client.first_name} {ranking.client.last_name or ''} - "
                    f"{ranking.referral_reservations_count} reservas (S/{ranking.total_referral_revenue})"
                )

    def get_months_display(self, month):
        """Convierte número de mes a nombre en español"""
        months = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        return months.get(month, month)