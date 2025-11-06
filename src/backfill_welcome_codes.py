#!/usr/bin/env python
"""
Script para regenerar códigos de bienvenida NULL en producción.

Este script corrige el problema donde códigos WELCOME-XXXXXX se guardaron como NULL
debido al límite de max_length=20 en el campo code con MySQL/MariaDB.

Uso:
    python src/backfill_welcome_codes.py [--dry-run]

Opciones:
    --dry-run    Muestra qué se haría sin hacer cambios
"""

import os
import sys
import django
import random
import string

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.property.pricing_models import DiscountCode
from django.db.models import Q


def generate_unique_welcome_code():
    """Genera un código WELCOME único"""
    max_attempts = 10
    attempts = 0
    
    while attempts < max_attempts:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"WELCOME-{suffix}"
        
        # Verificar que no existe
        if not DiscountCode.objects.filter(code=code).exists():
            return code
        
        attempts += 1
    
    raise ValueError("No se pudo generar un código único después de 10 intentos")


def backfill_null_welcome_codes(dry_run=False):
    """Regenera códigos de bienvenida que están NULL"""
    
    print("🔍 Buscando códigos de descuento de bienvenida con code=NULL...")
    
    # Encontrar todos los códigos de bienvenida con code NULL
    null_codes = DiscountCode.objects.filter(
        Q(code__isnull=True) | Q(code=''),
        description__icontains='bienvenida',
        deleted=False
    )
    
    total_found = null_codes.count()
    print(f"📊 Encontrados {total_found} códigos NULL para regenerar\n")
    
    if total_found == 0:
        print("✅ ¡No hay códigos NULL! Todo está correcto.")
        return
    
    if dry_run:
        print("🔍 MODO DRY-RUN: Mostrando qué se haría sin hacer cambios\n")
    
    regenerated_count = 0
    failed_count = 0
    
    for discount_code in null_codes:
        try:
            new_code = generate_unique_welcome_code()
            
            if dry_run:
                print(f"  [DRY-RUN] Regeneraría: ID={discount_code.id}, Nuevo código: {new_code}")
                print(f"            Descripción: {discount_code.description[:60]}...")
            else:
                # Actualizar el código
                discount_code.code = new_code
                discount_code.save()
                
                print(f"  ✅ Regenerado: ID={discount_code.id}, Código: {new_code}")
                print(f"     Descripción: {discount_code.description[:60]}...")
            
            regenerated_count += 1
            
        except Exception as e:
            failed_count += 1
            print(f"  ❌ Error en ID={discount_code.id}: {str(e)}")
    
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN:")
    print(f"   Total encontrados:  {total_found}")
    print(f"   Regenerados:        {regenerated_count}")
    print(f"   Fallidos:           {failed_count}")
    
    if dry_run:
        print(f"\n💡 Ejecuta sin --dry-run para aplicar los cambios")
    else:
        print(f"\n✅ Backfill completado exitosamente!")
        print(f"\n⚠️  IMPORTANTE: Notifica a los clientes afectados de sus nuevos códigos")
        print(f"    Puedes obtener la lista de clientes con:")
        print(f"    SELECT * FROM clients_clients WHERE welcome_discount_issued = TRUE;")


if __name__ == '__main__':
    # Verificar argumentos
    dry_run = '--dry-run' in sys.argv
    
    print("="*60)
    print("🔧 BACKFILL DE CÓDIGOS DE BIENVENIDA NULL")
    print("="*60)
    print()
    
    try:
        backfill_null_welcome_codes(dry_run=dry_run)
    except KeyboardInterrupt:
        print("\n\n⚠️  Proceso interrumpido por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error fatal: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
