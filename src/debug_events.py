import os
import django
import sys

# Configurar Django
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.events.models import Event
from django.utils import timezone

print("🔍 DIAGNÓSTICO DE EVENTOS EN PRODUCCIÓN")
print("=" * 50)

now = timezone.now()
print(f"⏰ Fecha actual: {now}")
print()

# Contar todos los eventos
total_events = Event.objects.count()
print(f"📊 TOTAL de eventos en BD: {total_events}")

if total_events == 0:
    print("❌ NO HAY EVENTOS EN LA BASE DE DATOS")
    exit()

print()
print("🔍 ANÁLISIS DE FILTROS:")
print("-" * 30)

# Verificar cada filtro paso a paso
all_events = Event.objects.all()
print(f"1️⃣ Todos los eventos: {all_events.count()}")

not_deleted = all_events.filter(deleted=False)
print(f"2️⃣ No eliminados (deleted=False): {not_deleted.count()}")

active = not_deleted.filter(is_active=True)
print(f"3️⃣ Activos (is_active=True): {active.count()}")

public = active.filter(is_public=True)
print(f"4️⃣ Públicos (is_public=True): {public.count()}")

published = public.filter(status=Event.EventStatus.PUBLISHED)
print(f"5️⃣ Publicados (status=PUBLISHED): {published.count()}")

upcoming = published.filter(start_date__gt=now)
print(f"6️⃣ Futuros (start_date > ahora): {upcoming.count()}")

print()
print("📋 DETALLES DE EVENTOS:")
print("-" * 30)

for i, event in enumerate(all_events[:5], 1):
    print(f"{i}. {event.title}")
    print(f"   - deleted: {event.deleted}")
    print(f"   - is_active: {event.is_active}")
    print(f"   - is_public: {event.is_public}")
    print(f"   - status: {event.status}")
    print(f"   - start_date: {event.start_date}")
    print(f"   - ¿Es futuro?: {event.start_date > now if event.start_date else 'Sin fecha'}")
    print()

print("🎯 EVENTOS QUE PASAN TODOS LOS FILTROS:")
print("-" * 40)
final_events = upcoming
for event in final_events:
    print(f"✅ {event.title} - {event.start_date}")

if final_events.count() == 0:
    print("❌ NINGÚN EVENTO PASA TODOS LOS FILTROS")
    print()
    print("🔧 POSIBLES SOLUCIONES:")
    print("- Verificar que is_active=True")
    print("- Verificar que is_public=True") 
    print("- Verificar que status='published'")
    print("- Verificar que start_date sea futuro")
