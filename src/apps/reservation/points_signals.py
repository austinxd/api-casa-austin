from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from datetime import datetime, timedelta
from django.utils import timezone
from .models import Reservation
from apps.clients.models import Clients, ReferralPointsConfig, Achievement, ClientAchievement
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Reservation)
def assign_points_after_checkout(sender, instance, created, **kwargs):
    """
    Asigna puntos al cliente después del checkout de la reserva
    Solo asigna puntos para reservas de Austin (origin='aus') con cliente válido
    """
    if not instance.client:
        return

    # Solo asignar puntos para reservas de Austin y Cliente Web
    if instance.origin not in ['aus', 'client']:
        return

    # Verificar que no sea cliente de mantenimiento o AirBnB
    if instance.client.first_name in ['Mantenimiento', 'AirBnB']:
        return

    # Verificar que la reserva tenga precio válido
    if not instance.price_sol or instance.price_sol <= 0:
        return

    # Solo asignar puntos después del checkout (verificar que ya pasó la fecha)
    today = timezone.now().date()
    if instance.check_out_date > today:
        return  # Aún no es checkout

    # Verificar si ya se asignaron puntos para esta reserva
    from apps.clients.models import ClientPoints
    existing_points = ClientPoints.objects.filter(
        client=instance.client,
        reservation=instance,
        transaction_type=ClientPoints.TransactionType.EARNED,
        deleted=False).exists()

    if existing_points:
        return  # Ya se asignaron puntos

    # Calcular precio efectivo pagado (descontando puntos canjeados)
    effective_price = float(instance.price_sol)

    # Verificar si se canjearon puntos en esta reserva
    points_redeemed = float(instance.points_redeemed or 0)
    if points_redeemed > 0:
        effective_price -= points_redeemed

    # Calcular y asignar puntos (5% del precio efectivo pagado)
    points_to_add = instance.client.calculate_points_from_reservation(
        effective_price)

    if points_to_add > 0:
        instance.client.add_points(
            points=points_to_add,
            reservation=instance,
            description=
            f"Puntos ganados por reserva #{instance.id} - {instance.property.name} (precio efectivo: S/{effective_price:.2f})"
        )

        print(
            f"Puntos asignados: {points_to_add} puntos para cliente {instance.client.first_name} {instance.client.last_name}"
        )

        # Asignar puntos por referido si aplica
        if instance.client.referred_by:
            try:
                from apps.clients.models import ReferralPointsConfig
                from decimal import Decimal

                referral_config = ReferralPointsConfig.get_current_config()
                if referral_config and referral_config.is_active:
                    # Calcular puntos de referido basado en el porcentaje del valor de la reserva
                    referral_points = (Decimal(str(effective_price)) * referral_config.percentage) / Decimal('100')

                    if referral_points > 0:
                        # Asignar puntos al cliente que refirió
                        instance.client.referred_by.add_referral_points(
                            points=referral_points,
                            reservation=instance,
                            referred_client=instance.client,
                            description=f"Puntos por referido: {instance.client.first_name} {instance.client.last_name} - Reserva #{instance.id} ({referral_config.percentage}% de S/{effective_price:.2f})"
                        )

                        print(
                            f"Puntos de referido asignados: {referral_points} puntos para {instance.client.referred_by.first_name} {instance.client.referred_by.last_name} "
                            f"(referido: {instance.client.first_name} {instance.client.last_name}) - {referral_config.percentage}% de S/{effective_price:.2f}"
                        )

                        logger.debug(f"Puntos por referido procesados: {instance.client.referred_by.first_name} recibió {referral_points} puntos por referir a {instance.client.first_name}")

            except Exception as e:
                logger.error(f"Error procesando puntos por referido: {str(e)}")

        # Verificar logros para ambos clientes después de procesar puntos y reservas
        try:
            # Verificar logros para el cliente que hizo la reserva
            check_and_assign_achievements(instance.client.id)

            # Verificar logros para el cliente que refirió (si existe)
            if instance.client.referred_by:
                check_and_assign_achievements(instance.client.referred_by.id)

        except Exception as e:
            logger.error(f"Error verificando logros después de reserva: {str(e)}")


@receiver(post_delete, sender=Reservation)
def remove_points_after_delete(sender, instance, **kwargs):
    """
    Remueve puntos y logros asociados a una reserva eliminada.
    """
    if not instance.client:
        return

    # Solo procesar si la reserva es de Austin o Cliente Web
    if instance.origin not in ['aus', 'client']:
        return

    # Solo remover puntos si se habían asignado previamente
    from apps.clients.models import ClientPoints
    points_to_remove = ClientPoints.objects.filter(
        client=instance.client,
        reservation=instance,
        transaction_type=ClientPoints.TransactionType.EARNED,
        deleted=False)

    if points_to_remove.exists():
        total_points_removed = 0
        for point_entry in points_to_remove:
            total_points_removed += point_entry.points
            point_entry.deleted = True
            point_entry.save()
            logger.info(f"Puntos removidos por eliminación de reserva: {point_entry.points} puntos de la reserva #{instance.id} para {instance.client.first_name}")

        print(f"Total de puntos removidos: {total_points_removed} puntos para el cliente {instance.client.first_name} {instance.client.last_name}")

        # Re-verificar logros después de remover puntos
        try:
            check_and_assign_achievements(instance.client.id)
            if instance.client.referred_by:
                check_and_assign_achievements(instance.client.referred_by.id)
        except Exception as e:
            logger.error(f"Error verificando logros después de eliminar reserva: {str(e)}")


# --- Funciones de Señales de Logros ---

def check_and_assign_achievements(client_id):
    """Verificar y asignar logros basados en las estadísticas actuales del cliente"""
    from django.db import transaction

    try:
        from apps.clients.models import Clients, Achievement, ClientAchievement

        with transaction.atomic():
            client = Clients.objects.get(id=client_id, deleted=False)
            logger.debug(f"🔄 Verificando logros para cliente {client_id}")

            # Obtener todos los logros disponibles
            achievements = Achievement.objects.filter(deleted=False, is_active=True)

            achievements_assigned = 0

            for achievement in achievements:
                # Verificar si el cliente ya tiene el logro con select_for_update para evitar race conditions
                existing_achievement = ClientAchievement.objects.select_for_update().filter(
                    client=client,
                    achievement=achievement,
                    deleted=False
                ).first()

                if achievement.check_client_qualifies(client):
                    if not existing_achievement:
                        try:
                            # Usar get_or_create para manejar duplicados
                            client_achievement, created = ClientAchievement.objects.get_or_create(
                                client=client,
                                achievement=achievement,
                                defaults={'deleted': False}
                            )

                            if created:
                                logger.info(f"✅ Logro '{achievement.name}' asignado a cliente {client.id}")
                                achievements_assigned += 1
                            else:
                                logger.debug(f"🔄 Cliente {client.id} ya tiene el logro '{achievement.name}' (creado concurrentemente)")

                        except Exception as create_error:
                            logger.warning(f"⚠️ Error creando logro '{achievement.name}' para cliente {client.id}: {str(create_error)}")
                            # Verificar si el logro ya existe después del error
                            if ClientAchievement.objects.filter(
                                client=client,
                                achievement=achievement,
                                deleted=False
                            ).exists():
                                logger.debug(f"🔄 Cliente {client.id} ya tiene el logro '{achievement.name}' (verificado después del error)")
                    else:
                        logger.debug(f"🔄 Cliente {client.id} ya tiene el logro '{achievement.name}'")
                else:
                    logger.debug(f"❌ Cliente {client.id} no cumple requisitos para '{achievement.name}'")

            logger.info(f"📊 Verificación de logros completada para cliente {client_id}. Logros asignados: {achievements_assigned}")

    except Exception as e:
        logger.error(f"❌ Error verificando logros para cliente {client_id}: {str(e)}")
        # No propagar la excepción para evitar romper el flujo principal