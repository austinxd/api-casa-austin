"""Inserta o actualiza la sección de FECHAS VAGAS en el system prompt
sin sobrescribir el resto. Pensado para deployar el fix P1 sin perder
ediciones manuales hechas en Django admin.

Si la sección ya existe, la reemplaza. Si no, la inserta justo
después del bloque "FECHA DE SALIDA NO PROPORCIONADA".

Uso:
    python manage.py patch_vague_dates
    python manage.py patch_vague_dates --dry-run   # solo muestra el diff
"""
import re
from django.core.management.base import BaseCommand
from apps.chatbot.models import ChatbotConfiguration


VAGUE_DATES_BLOCK = """
## ⚠️ FECHAS VAGAS / RANGOS AMPLIOS (CRÍTICO — ANTI ABANDONO):
Si el cliente da un rango amplio sin fecha exacta ("para enero", "fines de junio", "verano",
"este mes", "el próximo mes", "ya cuando podamos"), NO pidas fecha exacta antes de cotizar.
El análisis de conversaciones mostró que pedir fecha exacta 2-3 veces hace que el cliente
abandone. Para no perder la venta:

1) Si tenés personas (aunque sea aproximado) → ASUMI una fecha tentativa razonable y cotizá
   con check_availability. Luego aclarale "Esto es para [fecha], ¿querés ver otra opción?"

2) Mapeo de fechas tentativas:
   - "enero" / "este mes (enero)" → 2do sábado de enero a domingo
   - "febrero" → 2do sábado del mes
   - "fines de junio" → último sábado a domingo de junio
   - "primer fin de junio" → primer sábado a domingo de junio
   - "verano" → 2do sábado de enero a domingo (verano PE = ene-mar)
   - "fin de semana largo" → próximo fin de semana del calendario
   - "próximo mes" → 2do sábado del mes siguiente al actual
   - "este finde" → próximo viernes a domingo
   - Si dice año pero no mes ("para 2026") → preguntá UNA vez "¿algún mes en particular?"

3) Si NO tenés personas todavía → usá check_calendar(from=primer día del período,
   to=último día) para mostrar disponibilidad general del rango, y pedí personas UNA vez.

4) FÓRMULA cuando cotizás con fecha tentativa:
   "Para [grupo] en [período], te dejo el precio aproximado para [fecha tentativa]:
    [resultado de check_availability]
    Si tenés otras fechas en mente, decime y armo la cotización exacta."

5) GRUPOS GRANDES (+25 personas) con fecha vaga:
   - NO pidas "fecha exacta" repetidamente. La gente que planea evento grande aún
     no tiene fecha cerrada. Cotiza con fecha tentativa.
   - Recomendá Casa Austin 3 directo (tiene la mayor capacidad).
   - Mencioná posibilidad de combinar 2 casas si pasan de 100.

EJEMPLO REAL que NO se cerró por pedir fecha exacta (mejorá esto):
❌ Cliente: "Es para enero, aproximadamente 35 personas"
   Bot: "¿Tienes fechas específicas en mente para tu reserva?"
   → Cliente abandona.

✅ Cliente: "Es para enero, aproximadamente 35 personas"
   Bot: "Para enero con 35 personas, Casa Austin 3 es ideal. Te paso el precio
        aproximado para el 2do fin de semana de enero (sáb-dom):
        [check_availability(2do sábado enero, domingo, 35)]
        Si tenés otra fecha en mente, decime y la armamos exacta. 😊"
"""

START_MARKER = "## ⚠️ FECHAS VAGAS / RANGOS AMPLIOS"
ANCHOR_BEFORE = "NUNCA respondas \"¿quieres reservar?\" sin haber mostrado precios primero."


class Command(BaseCommand):
    help = "Patch quirúrgico: inserta sección FECHAS VAGAS en el system prompt activo."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra cambios.')

    def handle(self, *args, **opts):
        config = ChatbotConfiguration.objects.filter(is_active=True).first()
        if not config:
            self.stdout.write(self.style.ERROR("No hay ChatbotConfiguration activa."))
            return

        prompt = config.system_prompt or ""

        # ¿Ya existe la sección?
        if START_MARKER in prompt:
            # Reemplazar el bloque existente: desde el marker hasta la próxima
            # sección (## algo) o fin del prompt.
            pattern = re.compile(
                re.escape(START_MARKER) + r'.*?(?=\n##\s|$)',
                re.DOTALL,
            )
            new_prompt = pattern.sub(VAGUE_DATES_BLOCK.strip(), prompt)
            action = "REEMPLAZADO"
        elif ANCHOR_BEFORE in prompt:
            # Insertar después del anchor (línea completa).
            idx = prompt.find(ANCHOR_BEFORE) + len(ANCHOR_BEFORE)
            new_prompt = prompt[:idx] + "\n" + VAGUE_DATES_BLOCK + prompt[idx:]
            action = "INSERTADO"
        else:
            # Si no encontramos el anchor, lo metemos al final con un separador.
            new_prompt = prompt.rstrip() + "\n\n" + VAGUE_DATES_BLOCK
            action = "APPENDED (no anchor)"

        diff_size = len(new_prompt) - len(prompt)
        self.stdout.write(f"Acción: {action}")
        self.stdout.write(f"Tamaño actual: {len(prompt)} chars")
        self.stdout.write(f"Tamaño nuevo:  {len(new_prompt)} chars (Δ {diff_size:+d})")

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING("--dry-run: no se guardó nada."))
            return

        config.system_prompt = new_prompt
        config.save(update_fields=['system_prompt', 'updated'])
        self.stdout.write(self.style.SUCCESS("System prompt actualizado correctamente."))
