from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clients.models import Clients, ClientPoints, ReferralPointsConfig
from apps.reservation.models import Reservation
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Asigna puntos automáticamente a reservas que ya pasaron checkout'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula la asignación sin guardar cambios',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        today = timezone.now().date()
        
        if dry_run:
            self.stdout.write(self.style.WARNING("🔍 Modo DRY RUN - No se guardarán cambios\n"))
        
        # Buscar reservas que ya pasaron checkout pero no tienen puntos asignados
        pending_reservations = Reservation.objects.filter(
            origin__in=['aus', 'client'],
            check_out_date__lt=today,  # Ya pasó el checkout
            client__isnull=False,
            price_sol__gt=0,
            deleted=False
        ).exclude(
            client__first_name__in=['Mantenimiento', 'AirBnB']
        ).select_related('client', 'property')

        points_assigned = 0
        referral_points_assigned = 0
        reservations_processed = 0

        for reservation in pending_reservations:
            # Verificar si ya tiene puntos asignados
            existing_points = ClientPoints.objects.filter(
                client=reservation.client,
                reservation=reservation,
                transaction_type=ClientPoints.TransactionType.EARNED,
                deleted=False
            ).exists()

            if existing_points:
                continue

            # Calcular precio efectivo pagado (descontando puntos canjeados)
            effective_price = float(reservation.price_sol)
            points_redeemed = float(reservation.points_redeemed or 0)
            if points_redeemed > 0:
                effective_price -= points_redeemed

            # Calcular y asignar puntos (5% del precio efectivo pagado)
            points_to_add = reservation.client.calculate_points_from_reservation(effective_price)
            
            if points_to_add > 0:
                if not dry_run:
                    # Asignar puntos al cliente
                    reservation.client.add_points(
                        points=points_to_add,
                        reservation=reservation,
                        description=f"Puntos ganados por reserva #{reservation.id} - {reservation.property.name} (precio efectivo: S/{effective_price:.2f})"
                    )

                    # 📊 ACTIVITY FEED: Crear actividad para puntos ganados
                    try:
                        from apps.events.models import ActivityFeed, ActivityFeedConfig
                        
                        if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.POINTS_EARNED):
                            is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.POINTS_EARNED)
                            importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.POINTS_EARNED)
                            
                            ActivityFeed.create_activity(
                                activity_type=ActivityFeed.ActivityType.POINTS_EARNED,
                                client=reservation.client,
                                property_location=reservation.property,
                                is_public=is_public,
                                importance_level=importance,
                                activity_data={
                                    'points': float(points_to_add),
                                    'reason': 'una reserva',
                                    'property_name': reservation.property.name,
                                    'reservation_id': str(reservation.id),
                                    'effective_price': effective_price
                                }
                            )
                        logger.debug(f"Actividad de puntos creada para cliente {reservation.client.id}")
                    except Exception as e:
                        logger.error(f"Error creando actividad de puntos: {str(e)}")
                
                points_assigned += points_to_add
                reservations_processed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ {points_to_add:.2f} puntos asignados a {reservation.client.first_name} {reservation.client.last_name} "
                        f"(Reserva #{reservation.id}, precio efectivo: S/{effective_price:.2f})"
                    )
                )

                # Asignar puntos por referido si aplica
                if reservation.client.referred_by:
                    try:
                        referral_config = ReferralPointsConfig.get_current_config()
                        if referral_config and referral_config.is_active:
                            # Calcular puntos de referido basado en el porcentaje del valor de la reserva
                            referral_points = (Decimal(str(effective_price)) * referral_config.percentage) / Decimal('100')

                            if referral_points > 0:
                                if not dry_run:
                                    # Asignar puntos al cliente que refirió
                                    reservation.client.referred_by.add_referral_points(
                                        points=referral_points,
                                        reservation=reservation,
                                        referred_client=reservation.client,
                                        description=f"Puntos por referido: {reservation.client.first_name} {reservation.client.last_name} - Reserva #{reservation.id} ({referral_config.percentage}% de S/{effective_price:.2f})"
                                    )

                                    # 📊 ACTIVITY FEED: Crear actividad para puntos por referido
                                    try:
                                        from apps.events.models import ActivityFeed, ActivityFeedConfig
                                        
                                        if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.POINTS_EARNED):
                                            is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.POINTS_EARNED)
                                            importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.POINTS_EARNED)
                                            
                                            ActivityFeed.create_activity(
                                                activity_type=ActivityFeed.ActivityType.POINTS_EARNED,
                                                client=reservation.client.referred_by,
                                                property_location=reservation.property,
                                                is_public=is_public,
                                                importance_level=importance,
                                                activity_data={
                                                    'points': float(referral_points),
                                                    'reason': f'referir a {reservation.client.first_name} {reservation.client.last_name[0].upper()}.' if reservation.client.last_name else reservation.client.first_name,
                                                    'property_name': reservation.property.name,
                                                    'reservation_id': str(reservation.id),
                                                    'is_referral': True
                                                }
                                            )
                                        logger.debug(f"Actividad de referido creada para cliente {reservation.client.referred_by.id}")
                                    except Exception as e:
                                        logger.error(f"Error creando actividad de referido: {str(e)}")

                                referral_points_assigned += float(referral_points)

                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"   💰 {referral_points:.2f} puntos por referido a {reservation.client.referred_by.first_name} {reservation.client.referred_by.last_name} "
                                        f"({referral_config.percentage}% de S/{effective_price:.2f})"
                                    )
                                )
                    except Exception as e:
                        logger.error(f"Error procesando puntos por referido: {str(e)}")

                # Verificar logros (achievements)
                if not dry_run:
                    try:
                        from apps.reservation.points_signals import check_and_assign_achievements
                        
                        # Verificar logros para el cliente que hizo la reserva
                        check_and_assign_achievements(reservation.client.id)

                        # Verificar logros para el cliente que refirió (si existe)
                        if reservation.client.referred_by:
                            check_and_assign_achievements(reservation.client.referred_by.id)

                    except Exception as e:
                        logger.error(f"Error verificando logros después de reserva: {str(e)}")

        # Resumen final
        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎯 Proceso completado:\n"
                f"Reservas procesadas: {reservations_processed}\n"
                f"Total puntos asignados: {points_assigned:.2f}\n"
                f"Total puntos por referido: {referral_points_assigned:.2f}\n"
                f"Total general: {points_assigned + referral_points_assigned:.2f}"
            )
        )
