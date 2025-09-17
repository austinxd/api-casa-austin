import os
import django
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
import json

# Crear cliente de test
client = Client()

print("🔍 RESPUESTA COMPLETA DEL ENDPOINT")
print("=" * 50)

# Hacer request al endpoint
response = client.get('/api/v1/events/?status=upcoming')

print(f"📊 Status Code: {response.status_code}")
print(f"📏 Content Length: {len(response.content)}")
print(f"🗂️ Content Type: {response.get('Content-Type')}")
print()

if response.status_code == 200:
    try:
        data = response.json()
        print("📋 RESPUESTA JSON:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if 'results' in data:
            print(f"\n✅ EVENTOS ENCONTRADOS: {len(data['results'])}")
            for i, event in enumerate(data['results'], 1):
                print(f"{i}. {event.get('title', 'Sin título')}")
        else:
            print("❌ NO HAY CAMPO 'results' EN LA RESPUESTA")
            
    except json.JSONDecodeError as e:
        print(f"❌ ERROR AL PARSEAR JSON: {e}")
        print("📄 CONTENIDO RAW:")
        print(response.content.decode('utf-8')[:500] + "...")
else:
    print(f"❌ ERROR HTTP {response.status_code}")
    print(response.content.decode('utf-8'))
