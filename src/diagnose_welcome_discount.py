#!/usr/bin/env python
"""
Script de diagnóstico para problemas con códigos de descuento de bienvenida.

Uso:
    python src/diagnose_welcome_discount.py --email user@example.com
    python src/diagnose_welcome_discount.py --doc dni 12345678
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.clients.models import Clients
from apps.property.pricing_models import DiscountCode, WelcomeDiscountConfig


def diagnose_client(client):
    """Diagnostica el estado del código de bienvenida de un cliente"""
    print("\n" + "="*60)
    print("🔍 DIAGNÓSTICO DE CÓDIGO DE BIENVENIDA")
    print("="*60)
    
    # Información del cliente
    print(f"\n📋 Cliente:")
    print(f"   ID: {client.id}")
    print(f"   Nombre: {client.get_full_name() if hasattr(client, 'get_full_name') else client.first_name}")
    print(f"   Email: {client.email}")
    print(f"   Documento: {client.document_type} {client.number_doc}")
    
    # Estado del descuento de bienvenida
    print(f"\n🎁 Estado del Descuento de Bienvenida:")
    print(f"   welcome_discount_issued: {client.welcome_discount_issued}")
    print(f"   welcome_discount_issued_at: {client.welcome_discount_issued_at}")
    
    # Verificar promoción activa
    print(f"\n📢 Promoción Activa:")
    active_config = WelcomeDiscountConfig.get_active_config()
    if active_config:
        print(f"   ✅ SÍ - {active_config.name} ({active_config.discount_percentage}%)")
    else:
        print(f"   ❌ NO - No hay promoción activa")
    
    # Buscar códigos de descuento de bienvenida
    print(f"\n🎫 Códigos de Bienvenida Encontrados:")
    
    # Búsqueda 1: Por nombre completo
    full_name = client.get_full_name() if hasattr(client, 'get_full_name') else f"{client.first_name} {client.last_name}".strip()
    codes_by_name = DiscountCode.objects.filter(
        code__startswith='WELCOME-',
        description__icontains=full_name,
        deleted=False
    )
    
    # Búsqueda 2: Por email
    codes_by_email = DiscountCode.objects.filter(
        code__startswith='WELCOME-',
        description__icontains=client.email,
        deleted=False
    ) if client.email else DiscountCode.objects.none()
    
    # Búsqueda 3: Por fecha
    codes_by_date = DiscountCode.objects.none()
    if client.welcome_discount_issued_at:
        from datetime import timedelta
        date_from = client.welcome_discount_issued_at - timedelta(days=1)
        date_to = client.welcome_discount_issued_at + timedelta(days=1)
        codes_by_date = DiscountCode.objects.filter(
            code__startswith='WELCOME-',
            created__gte=date_from,
            created__lte=date_to,
            deleted=False,
            usage_limit=1
        )
    
    # Mostrar resultados
    all_codes = set(codes_by_name) | set(codes_by_email) | set(codes_by_date)
    
    if all_codes:
        for code in all_codes:
            status_icon = "✅" if code.is_active else "❌"
            code_value = code.code if code.code else "❌ NULL"
            print(f"   {status_icon} {code_value}")
            print(f"      Descripción: {code.description}")
            print(f"      Activo: {code.is_active}")
            print(f"      Usado: {code.used_count}/{code.usage_limit}")
            print(f"      Válido: {code.start_date} a {code.end_date}")
            print(f"      Creado: {code.created}")
            print()
    else:
        print(f"   ❌ No se encontraron códigos de bienvenida para este cliente")
    
    # Diagnóstico y recomendaciones
    print(f"\n💡 DIAGNÓSTICO:")
    
    if not client.welcome_discount_issued:
        print(f"   ⚠️  El cliente NO tiene welcome_discount_issued=True")
        if active_config:
            print(f"   ✅ Solución: Usar endpoint POST /api/v1/clients/client-auth/welcome-discount/")
        else:
            print(f"   ❌ No se puede generar código (no hay promoción activa)")
    elif not all_codes:
        print(f"   ⚠️  El cliente tiene el flag marcado pero NO tiene código en BD")
        print(f"   ✅ Solución: Ejecutar script de backfill: python src/backfill_welcome_codes.py")
    elif any(not c.code for c in all_codes):
        print(f"   ⚠️  Hay códigos pero con code=NULL")
        print(f"   ✅ Solución: Ejecutar script de backfill: python src/backfill_welcome_codes.py")
    else:
        print(f"   ✅ El cliente tiene código(s) de bienvenida válido(s)")
        if not any(c.is_active for c in all_codes):
            print(f"   ⚠️  Pero todos los códigos están inactivos")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Diagnosticar problemas con códigos de bienvenida')
    parser.add_argument('--email', help='Email del cliente')
    parser.add_argument('--doc', nargs=2, metavar=('TYPE', 'NUMBER'), help='Documento del cliente (tipo y número)')
    
    args = parser.parse_args()
    
    try:
        if args.email:
            client = Clients.objects.get(email=args.email, deleted=False)
        elif args.doc:
            doc_type, doc_number = args.doc
            client = Clients.objects.get(document_type=doc_type, number_doc=doc_number, deleted=False)
        else:
            print("❌ Debes proporcionar --email o --doc")
            sys.exit(1)
        
        diagnose_client(client)
        
    except Clients.DoesNotExist:
        print("❌ Cliente no encontrado")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
