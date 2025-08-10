from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import datetime, timedelta
from django.utils import timezone
from .models import Reservation


@receiver(post_save, sender=Reservation)
def assign_points_after_checkout(sender, instance, created, **kwargs):
    """
    Asigna puntos al cliente después del checkout de la reserva
    Solo asigna puntos para reservas de Austin (origin='aus') con cliente válido
    """
    if not instance.client:
        return

    # Solo asignar puntos para reservas de Austin
    if instance.origin != 'aus':
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
