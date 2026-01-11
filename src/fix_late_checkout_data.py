#!/usr/bin/env python
"""
Script para corregir reservas con datos inconsistentes de late_checkout.

El problema: Algunas reservas tienen late_checkout=True pero check_out_date == late_check_out_date,
cuando debería ser check_out_date = late_check_out_date + 1 día.

Este script corrige esas reservas.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import timedelta
from apps.reservation.models import Reservation


def fix_late_checkout_data():
    print('Buscando reservas con datos inconsistentes de late_checkout...')

    # Buscar reservas donde late_checkout=True, late_check_out_date existe,
    # y check_out_date == late_check_out_date (datos inconsistentes)
    inconsistent_reservations = Reservation.objects.filter(
        late_checkout=True,
        late_check_out_date__isnull=False,
        deleted=False
    )

    fixed_count = 0

    for res in inconsistent_reservations:
        if res.check_out_date == res.late_check_out_date:
            old_checkout = res.check_out_date
            new_checkout = res.late_check_out_date + timedelta(days=1)

            print(f'  Reserva #{res.id}:')
            print(f'    - Propiedad: {res.property.name if res.property else "N/A"}')
            print(f'    - Cliente: {res.client.first_name} {res.client.last_name}' if res.client else '    - Cliente: N/A')
            print(f'    - late_check_out_date: {res.late_check_out_date}')
            print(f'    - check_out_date (antes): {old_checkout}')
            print(f'    - check_out_date (corregido): {new_checkout}')

            res.check_out_date = new_checkout
            res._change_reason = "Script: Corrección de datos inconsistentes de late_checkout"
            res.save()

            fixed_count += 1
            print(f'    ✅ Corregida')

    if fixed_count == 0:
        print('No se encontraron reservas con datos inconsistentes.')
    else:
        print(f'\n✅ Se corrigieron {fixed_count} reservas.')


if __name__ == "__main__":
    fix_late_checkout_data()
