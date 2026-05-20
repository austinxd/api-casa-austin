"""Endpoints que alimentan el modal Negocio de jarvis.

Sprint 1 del rediseño del modal: convertir "lectores de datos" en
"misión control de ventas accionable".

Endpoints:
- GET  /api/v1/chatbot/intervention-opportunities/?limit=10
       → Top sesiones con score >= 40, ordenadas desc + acciones sugeridas.

- GET  /api/v1/chatbot/today-snapshot/
       → KPIs del día + deltas vs ayer + alertas + estado de las 4 casas.

- POST /api/v1/chatbot/quick-actions/
       Body: {session_id, action_id, **kwargs}
       → Ejecuta acción de quick_actions.py (link nuevo, descuento, escalar...).
"""
from datetime import time as time_cls, timedelta

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChatMessage, ChatSession
from .scoring import calculate_intervention_score
from .quick_actions import execute_action


class AdminInterventionOpportunitiesView(APIView):
    """GET /api/v1/chatbot/intervention-opportunities/?limit=10

    Devuelve sesiones donde una intervención manual probablemente
    cierre la venta. Ordenadas por score descendente.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get('limit', 10)), 50)
        except (ValueError, TypeError):
            limit = 10

        # Universo: sesiones ACTIVAS de los últimos 7 días con actividad reciente.
        # Filtramos primero por DB para no calcular score de miles de sesiones.
        cutoff = timezone.now() - timedelta(days=7)
        candidates = (
            ChatSession.objects.filter(
                deleted=False,
                last_message_at__gte=cutoff,
            )
            .exclude(status__in=['closed'])
            .select_related('client')
            .order_by('-last_message_at')[:200]  # cap razonable
        )

        opportunities = []
        for session in candidates:
            opp = calculate_intervention_score(session)
            if opp is not None:
                opportunities.append(opp)

        # Sort por score desc
        opportunities.sort(key=lambda o: o.score, reverse=True)
        top = opportunities[:limit]

        return Response({
            'count': len(top),
            'total_analyzed': len(candidates),
            'opportunities': [o.to_dict() for o in top],
        })


class AdminTodaySnapshotView(APIView):
    """GET /api/v1/chatbot/today-snapshot/

    Resumen del día para el modal home de jarvis. Cache 60s.
    """
    permission_classes = [IsAdminUser]
    _CACHE_KEY = 'chatbot:today_snapshot:v1'
    _CACHE_TTL = 60  # segundos

    def get(self, request):
        cached = cache.get(self._CACHE_KEY)
        if cached:
            return Response(cached)

        now = timezone.localtime(timezone.now())
        today = now.date()
        yesterday = today - timedelta(days=1)

        # KPIs hoy
        def kpis_for(d):
            start = timezone.make_aware(timezone.datetime.combine(d, time_cls.min))
            end = start + timedelta(days=1)
            sessions_qs = ChatSession.objects.filter(
                deleted=False, created__gte=start, created__lt=end,
            )
            sessions_total = sessions_qs.count()
            sessions_with_quote = sessions_qs.filter(quoted_at__isnull=False).count()
            # Magic links creados HOY
            from apps.clients.magic_link_models import ReservationMagicLink
            ml_qs = ReservationMagicLink.objects.filter(
                deleted=False, created__gte=start, created__lt=end,
            )
            ml_created = ml_qs.count()
            ml_opened = ml_qs.filter(use_count__gt=0).count()
            # Reservas pagadas creadas hoy (origin chatbot)
            from apps.reservation.models import Reservation
            reservations_paid = Reservation.objects.filter(
                deleted=False, status='approved',
                created__gte=start, created__lt=end,
            ).count()
            return {
                'sessions': sessions_total,
                'sessions_with_quote': sessions_with_quote,
                'magic_links_created': ml_created,
                'magic_links_opened': ml_opened,
                'reservations_paid': reservations_paid,
            }

        kpis_today = kpis_for(today)
        kpis_yesterday = kpis_for(yesterday)

        def pct_delta(a, b):
            if b == 0:
                return None if a == 0 else 100
            return round((a - b) / b * 100)

        deltas_percent = {
            k: pct_delta(kpis_today.get(k, 0), kpis_yesterday.get(k, 0))
            for k in kpis_today.keys()
        }

        # ─── Alertas ───
        alerts = []
        # 1) Conversaciones atascadas (≥20 msgs, sin cotización, activas últimas 24h)
        cutoff_24h = now - timedelta(hours=24)
        stuck = ChatSession.objects.filter(
            deleted=False,
            total_messages__gte=20,
            quoted_at__isnull=True,
            last_message_at__gte=cutoff_24h,
        ).count()
        if stuck:
            alerts.append({
                'type': 'stuck_sessions', 'level': 'warning', 'count': stuck,
                'message': f"{stuck} conversaciones con 20+ msgs sin cerrar cotización",
                'action_view': 'conversaciones', 'action_filter': 'stuck',
            })

        # 2) Magic links creados sin abrir (últimas 24h)
        from apps.clients.magic_link_models import ReservationMagicLink
        ml_unopened = ReservationMagicLink.objects.filter(
            deleted=False, created__gte=cutoff_24h, use_count=0,
        ).count()
        if ml_unopened >= 3:
            alerts.append({
                'type': 'links_not_opened', 'level': 'info', 'count': ml_unopened,
                'message': f"{ml_unopened} magic links creados hoy sin abrir",
            })

        # 3) Gaps del bot (preguntas sin resolver últimos 7 días, con texto repetido ≥3 veces)
        from .models import UnresolvedQuestion
        cutoff_7d = now - timedelta(days=7)
        try:
            top_unresolved = (
                UnresolvedQuestion.objects.filter(
                    deleted=False, created__gte=cutoff_7d, status='pending',
                )
                .values('question')
                .annotate(c=Count('id'))
                .order_by('-c')[:3]
            )
            for q in top_unresolved:
                if q['c'] >= 3:
                    short = (q['question'] or '')[:60]
                    alerts.append({
                        'type': 'bot_gap', 'level': 'warning', 'count': q['c'],
                        'message': f'Bot no resolvió: "{short}" ({q["c"]} veces)',
                    })
        except Exception:
            pass  # si UnresolvedQuestion no existe o falla, omitimos esta alerta

        # ─── Estado de las 4 casas ───
        # Reutilizamos lógica de ActiveReservationsView vía import directo.
        houses_today = self._build_houses_today(now)

        payload = {
            'date': today.isoformat(),
            'kpis_today': kpis_today,
            'kpis_yesterday': kpis_yesterday,
            'deltas_percent': deltas_percent,
            'alerts': alerts,
            'houses_today': houses_today,
        }
        cache.set(self._CACHE_KEY, payload, self._CACHE_TTL)
        return Response(payload)

    def _build_houses_today(self, now):
        """Estado actual de las 4 casas con foto + datos del huésped."""
        from apps.property.models import Property
        from apps.reservation.models import Reservation
        from apps.reservation.views import _client_extra_info

        today = now.date()
        checkin_t = time_cls(12, 0)
        checkout_t = time_cls(11, 0)

        properties = list(
            Property.objects.filter(deleted=False).order_by('name')
        )

        result = []
        for prop in properties:
            # ¿Reserva activa AHORA?
            active = Reservation.objects.filter(
                deleted=False, status='approved', property=prop,
                check_in_date__lte=today, check_out_date__gte=today,
            ).select_related('client').first()

            status = 'free'
            client_name = None
            client_photo_b64 = None
            guests = None
            check_out_date = None
            next_event = None

            if active:
                # Validar horarios
                in_range = True
                if active.check_in_date == today and now.time() < checkin_t:
                    in_range = False
                if (active.check_out_date == today
                        and active.check_in_date < today
                        and now.time() >= checkout_t):
                    in_range = False
                if in_range:
                    status = 'occupied'
                    if active.client_id:
                        client_name = (
                            f"{active.client.first_name or ''} {active.client.last_name or ''}".strip()
                            or "Sin nombre"
                        )
                        extra = _client_extra_info(active.client, include_photo=True)
                        client_photo_b64 = extra['photo_b64']
                    guests = active.guests
                    check_out_date = active.check_out_date.isoformat()
                    days_left = (active.check_out_date - today).days
                    next_event = (
                        f"Check-out hoy" if days_left == 0
                        else f"Check-out en {days_left} día{'s' if days_left != 1 else ''}"
                    )

            # ¿Check-in pendiente para hoy?
            if status == 'free':
                pending = Reservation.objects.filter(
                    deleted=False, status='approved', property=prop,
                    check_in_date=today,
                ).select_related('client').first()
                if pending:
                    status = 'checkin_pending'
                    if pending.client_id:
                        client_name = (
                            f"{pending.client.first_name or ''} {pending.client.last_name or ''}".strip()
                            or "Sin nombre"
                        )
                    guests = pending.guests
                    next_event = "Check-in 12:00 PM"

            result.append({
                'property_id': str(prop.id),
                'property_name': prop.name,
                'status': status,
                'client_name': client_name,
                'client_photo_b64': client_photo_b64,
                'guests': guests,
                'check_out_date': check_out_date,
                'next_event': next_event,
            })
        return result


class AdminQuickActionView(APIView):
    """POST /api/v1/chatbot/quick-actions/

    Body: {"session_id": "<uuid>", "action_id": "send_fresh_link", ...kwargs}
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        session_id = request.data.get('session_id')
        action_id = request.data.get('action_id')
        if not session_id or not action_id:
            return Response(
                {'success': False, 'error': 'missing_params',
                 'result_detail': 'session_id y action_id son requeridos.'},
                status=400,
            )

        try:
            session = ChatSession.objects.select_related('client').get(
                id=session_id, deleted=False,
            )
        except ChatSession.DoesNotExist:
            return Response(
                {'success': False, 'error': 'session_not_found',
                 'result_detail': f'Sesión {session_id} no existe.'},
                status=404,
            )

        kwargs = {k: v for k, v in request.data.items() if k not in ('session_id', 'action_id')}
        result = execute_action(action_id, session, **kwargs)
        status_code = 200 if result.get('success') else 400
        return Response(result, status=status_code)
