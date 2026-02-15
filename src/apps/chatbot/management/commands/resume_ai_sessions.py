"""
Cron cada 5 minutos: reactiva la IA en sesiones donde ai_resume_at ya pasó.

Uso: python manage.py resume_ai_sessions
Cron: */5 * * * * cd /path/to/project && python manage.py resume_ai_sessions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatSession


class Command(BaseCommand):
    help = 'Reactiva la IA en sesiones donde el tiempo de pausa ha expirado'

    def handle(self, *args, **options):
        now = timezone.now()

        sessions = ChatSession.objects.filter(
            ai_enabled=False,
            ai_resume_at__isnull=False,
            ai_resume_at__lte=now,
            deleted=False,
        ).exclude(status='closed')

        count = sessions.count()

        if count == 0:
            self.stdout.write('No hay sesiones para reactivar.')
            return

        sessions.update(
            ai_enabled=True,
            status=ChatSession.StatusChoices.ACTIVE,
            ai_paused_at=None,
            ai_paused_by=None,
            ai_resume_at=None,
        )

        self.stdout.write(self.style.SUCCESS(
            f'{count} sesiones reactivadas con IA.'
        ))
