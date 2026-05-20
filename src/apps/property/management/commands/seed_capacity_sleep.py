"""Carga los valores reales de capacity_sleep para cada casa.

capacity_sleep = cantidad de gente que puede DORMIR en camas reales.
Es info INTERNA (admin/dashboards) — el chatbot no se la dice al
cliente. El cliente sigue viendo capacity_max (capacidad para evento).

Valores acordados con el dueño (2026-05-20):
  Casa Austin 1: 15 (igual a capacity_max)
  Casa Austin 2: 20
  Casa Austin 3: 20
  Casa Austin 4: 20

Uso:
    python manage.py seed_capacity_sleep
"""
from django.core.management.base import BaseCommand
from apps.property.models import Property


VALUES = {
    "Casa Austin 1": 15,
    "Casa Austin 2": 20,
    "Casa Austin 3": 20,
    "Casa Austin 4": 20,
}


class Command(BaseCommand):
    help = "Carga capacity_sleep (camas reales) en cada propiedad."

    def handle(self, *args, **opts):
        for name, sleep in VALUES.items():
            try:
                p = Property.objects.get(name=name, deleted=False)
            except Property.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"⚠ No encontré '{name}', salteando."))
                continue
            previous = p.capacity_sleep
            p.capacity_sleep = sleep
            p.save(update_fields=['capacity_sleep', 'updated'])
            self.stdout.write(self.style.SUCCESS(
                f"✓ {name}: capacity_sleep {previous} → {sleep} (capacity_max={p.capacity_max})"
            ))
        self.stdout.write(self.style.SUCCESS("Listo."))
