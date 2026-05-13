"""Detecta sesiones donde el bot cayó al fallback de error
('ai_model=error') para que el equipo las revise manualmente.

Causa común reciente: bug del ChatCompletionMessage (fix 3b96494). Las
sesiones que crashearon recibieron el mensaje genérico
"En este momento no puedo procesar tu consulta..." y la conversación
suele quedar trunca.

Uso:
    python manage.py chatbot_recover_error_sessions
    python manage.py chatbot_recover_error_sessions --days 7
    python manage.py chatbot_recover_error_sessions --days 7 --notify
    python manage.py chatbot_recover_error_sessions --csv > errores.csv
"""
import csv
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatMessage, ChatSession


class Command(BaseCommand):
    help = "Lista sesiones donde el bot respondió con el fallback de error."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Ventana hacia atrás en días (default 7).',
        )
        parser.add_argument(
            '--notify', action='store_true',
            help='Disparar notify_team(reason=needs_human_assist) por cada sesión afectada.',
        )
        parser.add_argument(
            '--csv', action='store_true',
            help='Output CSV (id, wa_id, nombre, fecha_error, último_mensaje_cliente).',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Limitar a N sesiones (0 = sin límite, default).',
        )

    def handle(self, *args, **opts):
        days = opts['days']
        do_notify = opts['notify']
        as_csv = opts['csv']
        limit = opts['limit']

        since = timezone.now() - timedelta(days=days)

        # Mensajes salientes del bot con ai_model='error' (fallback hardcoded)
        error_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            ai_model='error',
            created__gte=since,
        ).select_related('session', 'session__client').order_by('-created')

        if limit:
            error_msgs = error_msgs[:limit]

        # Agrupar por sesión: una sola fila por sesión, la primera vez que falló
        seen_sessions = {}
        for em in error_msgs:
            sid = em.session_id
            if sid not in seen_sessions:
                seen_sessions[sid] = em

        total = len(seen_sessions)

        if total == 0:
            if not as_csv:
                self.stdout.write(self.style.SUCCESS(
                    f"\nSin sesiones con error en los últimos {days} días. 🎉\n"
                ))
            return

        # CSV mode
        if as_csv:
            writer = csv.writer(sys.stdout)
            writer.writerow([
                'session_id', 'wa_id', 'wa_profile_name',
                'client_name', 'client_tel', 'error_at',
                'last_customer_msg', 'last_customer_msg_at',
                'session_status', 'ai_enabled',
            ])
            for sid, em in seen_sessions.items():
                s = em.session
                last_inbound = ChatMessage.objects.filter(
                    session=s, direction='inbound',
                    deleted=False, created__lt=em.created,
                ).order_by('-created').first()
                client = s.client
                writer.writerow([
                    str(sid),
                    s.wa_id,
                    s.wa_profile_name or '',
                    f"{client.first_name} {client.last_name or ''}".strip() if client else '',
                    client.tel_number if client else '',
                    em.created.isoformat(),
                    (last_inbound.content[:200] if last_inbound else ''),
                    (last_inbound.created.isoformat() if last_inbound else ''),
                    s.status, str(s.ai_enabled),
                ])
            return

        # Pretty print
        self.stdout.write(self.style.SUCCESS(
            f"\n=== Sesiones con error en últimos {days} días: {total} ===\n"
        ))

        notified = 0
        for i, (sid, em) in enumerate(seen_sessions.items(), 1):
            s = em.session
            last_inbound = ChatMessage.objects.filter(
                session=s, direction='inbound',
                deleted=False, created__lt=em.created,
            ).order_by('-created').first()
            client = s.client
            client_str = (
                f"{client.first_name} {client.last_name or ''}".strip()
                if client else '(sin cliente vinculado)'
            )

            self.stdout.write(
                f"{i:3}. [{em.created.strftime('%Y-%m-%d %H:%M')}] "
                f"{s.wa_id} · {s.wa_profile_name or client_str}"
            )
            self.stdout.write(
                f"     wa_id={s.wa_id} session={sid} "
                f"status={s.status} ai_enabled={s.ai_enabled}"
            )
            if last_inbound:
                preview = last_inbound.content[:160].replace('\n', ' ')
                self.stdout.write(
                    f"     Últ. msg cliente ({last_inbound.created.strftime('%H:%M')}): "
                    f"{preview!r}"
                )
            else:
                self.stdout.write(f"     Últ. msg cliente: (sin mensajes previos)")

            if do_notify:
                try:
                    from apps.chatbot.tool_executor import ToolExecutor
                    details = (
                        f"El bot respondió con el fallback de error en "
                        f"{em.created.strftime('%Y-%m-%d %H:%M')}. Cliente quedó "
                        f"sin respuesta. Último mensaje: "
                        f"\"{last_inbound.content[:200] if last_inbound else '(sin mensaje previo)'}\""
                    )
                    ToolExecutor(s).execute('notify_team', {
                        'reason': 'needs_human_assist',
                        'details': details,
                    })
                    notified += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"     ✗ Error notificando: {e}"
                    ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"--- Resumen: {total} sesiones afectadas ---"
        ))
        if do_notify:
            self.stdout.write(self.style.SUCCESS(
                f"Notificaciones disparadas: {notified}/{total}"
            ))
        else:
            self.stdout.write(self.style.NOTICE(
                "Para notificar al equipo: agrega --notify"
            ))
            self.stdout.write(self.style.NOTICE(
                "Para exportar CSV: --csv > errores.csv"
            ))
        self.stdout.write("")
