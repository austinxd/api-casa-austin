import os
import django
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.events.views import PublicEventListView
from django.test import RequestFactory
from django.utils import timezone
import json

print("🔍 PROBANDO VISTA DIRECTAMENTE")
print("=" * 40)

# Crear request factory
factory = RequestFactory()

# Crear request GET con parámetro status=upcoming
request = factory.get('/api/v1/events/?status=upcoming')

# Crear vista
view = PublicEventListView()
view.request = request

# Obtener queryset
queryset = view.get_queryset()

print(f"⏰ Timezone actual: {timezone.get_current_timezone()}")
print(f"🕐 Fecha/hora NOW: {timezone.now()}")
print()

print(f"📊 Queryset count: {queryset.count()}")
print()

print("📋 EVENTOS EN QUERYSET:")
for event in queryset:
    print(f"- {event.title}")
    print(f"  start_date: {event.start_date}")
    print(f"  timezone: {event.start_date.tzinfo}")
    print()

# Probar también sin filtro
print("\n" + "="*40)
print("🔍 PROBANDO SIN FILTRO status=upcoming")

request2 = factory.get('/api/v1/events/')
view2 = PublicEventListView()
view2.request = request2
queryset2 = view2.get_queryset()

print(f"📊 Queryset sin filtro: {queryset2.count()}")
for event in queryset2:
    print(f"- {event.title} ({event.start_date})")
