from django.core.management.base import BaseCommand
from apps.property.pricing_models import AutomaticDiscount
from apps.clients.models import Clients, ClientAchievement, Achievement
from decimal import Decimal
from datetime import date


class Command(BaseCommand):
    help = 'Debug automatic discounts and client achievements'

    def add_arguments(self, parser):
        parser.add_argument('--client-id', type=int, help='ID del cliente a verificar')
        parser.add_argument('--list-discounts', action='store_true', help='Listar todos los descuentos automáticos')
        parser.add_argument('--list-achievements', action='store_true', help='Listar todos los logros')
        parser.add_argument('--check-client', type=int, help='Verificar logros de un cliente específico')
        parser.add_argument('--debug-global', action='store_true', help='Debuggear descuentos globales sin cliente específico')


    def handle(self, *args, **options):
        if options['list_discounts']:
            self.list_automatic_discounts()

        if options['list_achievements']:
            self.list_achievements()

        if options['check_client']:
            self.check_client_achievements(options['check_client'])

        if options['client_id']:
            self.debug_client_discounts(options['client_id'])

        if options['debug_global']:
            self.debug_global_discounts()

    def list_automatic_discounts(self):
        self.stdout.write(self.style.SUCCESS('\n🤖 DESCUENTOS AUTOMÁTICOS ACTIVOS:'))
        discounts = AutomaticDiscount.objects.filter(is_active=True, deleted=False)

        for discount in discounts:
            self.stdout.write(f"\n📋 {discount.name}")
            self.stdout.write(f"   Trigger: {discount.get_trigger_display()}")
            self.stdout.write(f"   Porcentaje: {discount.discount_percentage}%")
            if discount.max_discount_usd:
                self.stdout.write(f"   Máximo: ${discount.max_discount_usd}")

            # Logros requeridos
            if discount.required_achievements.exists():
                achievements = list(discount.required_achievements.values_list('name', flat=True))
                self.stdout.write(f"   🏆 Logros requeridos: {', '.join(achievements)}")
            else:
                self.stdout.write(f"   🏆 Sin logros requeridos")

            # Restricciones de días
            if discount.restrict_weekdays:
                self.stdout.write(f"   📅 Solo días de semana")
            if discount.restrict_weekends:
                self.stdout.write(f"   📅 Solo fines de semana")

    def list_achievements(self):
        self.stdout.write(self.style.SUCCESS('\n🏆 LOGROS DISPONIBLES:'))
        achievements = Achievement.objects.filter(deleted=False)

        for achievement in achievements:
            # Contar cuántos clientes tienen este logro
            client_count = ClientAchievement.objects.filter(achievement=achievement).count()
            self.stdout.write(f"📜 {achievement.name} (ID: {achievement.id}) - {client_count} clientes")
            if achievement.description:
                self.stdout.write(f"   Descripción: {achievement.description}")

    def check_client_achievements(self, client_id):
        try:
            client = Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Cliente {client_id} no encontrado'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n👤 LOGROS DE {client.first_name} {client.last_name or ""} (ID: {client_id}):'))

        client_achievements = ClientAchievement.objects.filter(client=client)
        if client_achievements.exists():
            for ca in client_achievements:
                self.stdout.write(f"✅ {ca.achievement.name} (obtenido: {ca.created.strftime('%d/%m/%Y')})")
        else:
            self.stdout.write(f"❌ Este cliente no tiene logros registrados")

    def debug_client_discounts(self, client_id):
        try:
            client = Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Cliente {client_id} no encontrado'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n🔍 DEBUGGING DESCUENTOS PARA {client.first_name} {client.last_name or ""} (ID: {client_id}):'))

        # Información del cliente
        self.stdout.write(f"📅 Fecha de nacimiento: {client.date}")

        # Mostrar logros del cliente
        client_achievements = ClientAchievement.objects.filter(client=client)
        if client_achievements.exists():
            self.stdout.write(f"🏆 Logros del cliente:")
            for ca in client_achievements:
                self.stdout.write(f"   ✅ {ca.achievement.name} (ID: {ca.achievement.id})")
        else:
            self.stdout.write(f"🏆 Cliente sin logros registrados")

        # Evaluar cada descuento automático
        discounts = AutomaticDiscount.objects.filter(is_active=True, deleted=False)
        booking_date = date.today()

        self.stdout.write(f"\n🤖 Evaluando descuentos para fecha: {booking_date}")

        applicable_discounts = []

        for discount in discounts:
            self.stdout.write(f"\n🔍 Evaluando: '{discount.name}' - Trigger: '{discount.trigger}'")

            # Mostrar logros requeridos
            if discount.required_achievements.exists():
                required_names = list(discount.required_achievements.values_list('name', flat=True))
                self.stdout.write(f"🎯 Logros requeridos: {required_names}")

            try:
                applies, message = discount.applies_to_client(client, booking_date)

                if applies:
                    self.stdout.write(self.style.SUCCESS(f"✅ APLICA: {message}"))
                    # Calcular descuento con un monto ejemplo
                    test_amount = Decimal('100.00')
                    discount_amount = discount.calculate_discount(test_amount)
                    self.stdout.write(f"💰 Descuento en $100: ${discount_amount} ({discount.discount_percentage}%)")
                    applicable_discounts.append(discount)
                else:
                    self.stdout.write(self.style.ERROR(f"❌ NO APLICA: {message}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ ERROR: {str(e)}"))

        # Resumen
        if applicable_discounts:
            self.stdout.write(self.style.SUCCESS(f"\n🏆 DESCUENTOS APLICABLES: {len(applicable_discounts)}"))
            for discount in applicable_discounts:
                self.stdout.write(f"   ✅ {discount.name} ({discount.discount_percentage}%)")
        else:
            self.stdout.write(self.style.WARNING(f"\n❌ NO HAY DESCUENTOS APLICABLES para este cliente"))

    def debug_global_discounts(self):
        """Debug descuentos globales sin cliente específico"""
        self.stdout.write(self.style.SUCCESS('\n🌍 DEBUGGEANDO DESCUENTOS GLOBALES (SIN CLIENTE):'))

        from apps.clients.models import Achievement

        # Evaluar cada descuento automático para ver si aplica globalmente
        discounts = AutomaticDiscount.objects.filter(is_active=True, deleted=False)
        booking_date = date.today()

        self.stdout.write(f"\n🤖 Evaluando descuentos globales para fecha: {booking_date}")

        applicable_discounts = []

        for discount in discounts:
            self.stdout.write(f"\n🔍 Evaluando: '{discount.name}' - Trigger: '{discount.trigger}'")

            # Verificar si es un descuento global
            all_achievements = Achievement.objects.filter(deleted=False)
            required_achievements = discount.required_achievements.all()

            is_global_discount = (
                required_achievements.count() > 0 and
                required_achievements.count() == all_achievements.count() and
                set(required_achievements.values_list('id', flat=True)) == set(all_achievements.values_list('id', flat=True))
            )

            is_global_promotion = discount.trigger == discount.DiscountTrigger.GLOBAL_PROMOTION
            no_achievements_required = not discount.required_achievements.exists()

            if is_global_discount:
                self.stdout.write(f"🌍 Es un descuento GLOBAL (todos los niveles)")
            elif is_global_promotion:
                self.stdout.write(f"🌍 Es una PROMOCIÓN GLOBAL")
            elif no_achievements_required:
                self.stdout.write(f"🌍 NO requiere logros específicos - DEBE APLICAR GLOBALMENTE")
            else:
                required_names = list(discount.required_achievements.values_list('name', flat=True))
                self.stdout.write(f"🎯 Requiere logros específicos: {required_names} - NO aplica sin cliente")
                continue

            try:
                # Verificar si aplica globalmente
                applies, message = discount.applies_to_client_global(booking_date)

                if applies:
                    self.stdout.write(self.style.SUCCESS(f"✅ APLICA GLOBALMENTE: {message}"))
                    # Calcular descuento con un monto ejemplo
                    test_amount = Decimal('100.00')
                    discount_amount = discount.calculate_discount(test_amount)
                    self.stdout.write(f"💰 Descuento en $100: ${discount_amount} ({discount.discount_percentage}%)")
                    applicable_discounts.append(discount)
                else:
                    self.stdout.write(self.style.ERROR(f"❌ NO APLICA GLOBALMENTE: {message}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error evaluando descuento {discount.name}: {str(e)}"))

        self.stdout.write(f"\n🏆 RESUMEN DE DESCUENTOS GLOBALES APLICABLES:")
        if applicable_discounts:
            for discount in applicable_discounts:
                self.stdout.write(f"  ✅ {discount.name}")
        else:
            self.stdout.write(f"  ❌ Ningún descuento global aplicable")