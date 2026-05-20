"""Endpoints admin para buscar/consultar datos de clientes.

Usado por MCP para que el dueño/operador pregunte "datos del cliente con
DNI X" o "datos del cliente Juan Pérez" desde Claude Desktop.

Flujo:
1) Si pasan ?dni= y existe cliente local → devuelve datos locales + foto cacheada.
2) Si pasan ?dni= y NO existe cliente local pero es DNI peruano válido →
   llama ReniecService.lookup(include_photo=True), devuelve datos de Reniec
   con flag in_database=False.
3) Si pasan ?phone= o ?name= → busca cliente local por esos criterios.
4) Si pasan ?q= → prueba en orden: DNI exacto → teléfono → nombre icontains.
"""

import re
from datetime import date as _date

from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import Clients
from apps.reservation.views import _client_extra_info


def _serialize_client(client, include_photo=True):
    """Serializa un Client local con sus campos relevantes + foto del cache."""
    extra = _client_extra_info(client, include_photo=include_photo)
    return {
        'in_database': True,
        'id': str(client.id),
        'first_name': client.first_name,
        'last_name': client.last_name,
        'full_name': f"{client.first_name or ''} {client.last_name or ''}".strip(),
        'email': client.email,
        'tel_number': client.tel_number,
        'document_type': extra['document_type'],
        'number_doc': extra['number_doc'],
        'birthday': extra['birthday'],
        'age': extra['age'],
        'days_to_birthday': extra['days_to_birthday'],
        'sex': extra['sex'],
        'photo_b64': extra['photo_b64'],
        'photo_facebook': extra['photo_facebook'],
        'points_balance': float(client.points_balance or 0),
        'referral_code': (
            client.get_referral_code() if hasattr(client, 'get_referral_code')
            else (client.referral_code or '')
        ),
        'created': client.created.isoformat() if client.created else None,
    }


def _lookup_reniec_only(dni):
    """Para DNIs sin cliente local: llama Reniec on-demand y devuelve el dict."""
    from apps.reniec.service import ReniecService
    from apps.reniec.models import DNICache

    ok, data = ReniecService.lookup(
        dni=dni,
        source_app='mcp_lookup',
        include_photo=True,
        include_full_data=True,
    )
    if not ok:
        return None

    payload = data.get('data') if isinstance(data, dict) and 'data' in data else data
    cache = DNICache.objects.filter(dni=dni).first()
    photo_b64 = cache.foto if cache else None

    birthday_str = payload.get('fechaNacimiento') if isinstance(payload, dict) else None
    birthday = None
    age = None
    days_to_birthday = None
    if birthday_str:
        try:
            birthday = _date.fromisoformat(birthday_str[:10])
        except ValueError:
            birthday = None
    if birthday:
        today = _date.today()
        age = today.year - birthday.year - (
            (today.month, today.day) < (birthday.month, birthday.day)
        )
        try:
            next_bday = birthday.replace(year=today.year)
        except ValueError:
            next_bday = birthday.replace(year=today.year, day=28)
        if next_bday < today:
            try:
                next_bday = birthday.replace(year=today.year + 1)
            except ValueError:
                next_bday = birthday.replace(year=today.year + 1, day=28)
        days_to_birthday = (next_bday - today).days

    return {
        'in_database': False,
        'source': 'reniec',
        'document_type': 'dni',
        'number_doc': dni,
        'first_name': payload.get('nombres') if isinstance(payload, dict) else None,
        'last_name': (
            f"{payload.get('apellidoPaterno', '')} {payload.get('apellidoMaterno', '')}".strip()
            if isinstance(payload, dict) else None
        ),
        'full_name': (
            f"{payload.get('nombres', '')} {payload.get('apellidoPaterno', '')} {payload.get('apellidoMaterno', '')}".strip()
            if isinstance(payload, dict) else None
        ),
        'birthday': birthday.isoformat() if birthday else None,
        'age': age,
        'days_to_birthday': days_to_birthday,
        'sex': payload.get('sexo') if isinstance(payload, dict) else None,
        'photo_b64': photo_b64,
        'raw_reniec': payload,
    }


class AdminClientLookupView(APIView):
    """GET /api/v1/clients/admin/lookup/?dni=...&phone=...&name=...&q=...

    Devuelve un solo cliente (el match más probable) o lista si la búsqueda
    es ambigua. Si pasan ?dni= y no hay cliente local, consulta Reniec.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        dni = (request.query_params.get('dni') or '').strip()
        phone = (request.query_params.get('phone') or '').strip()
        name = (request.query_params.get('name') or '').strip()
        q = (request.query_params.get('q') or '').strip()

        if q and not (dni or phone or name):
            # Auto-routing por contenido de q
            if re.fullmatch(r'\d{8}', q):
                dni = q
            elif re.fullmatch(r'\+?\d{6,}', q):
                phone = q
            else:
                name = q

        if not (dni or phone or name):
            return Response(
                {'error': 'Pasá al menos uno de: dni, phone, name, q'},
                status=400,
            )

        # 1) Lookup por DNI / documento exacto
        if dni:
            client = Clients.objects.filter(
                deleted=False, document_type='dni', number_doc=dni,
            ).first()
            if client:
                return Response(_serialize_client(client))
            # No existe local — consultar Reniec si es DNI peruano (8 dígitos)
            if re.fullmatch(r'\d{8}', dni):
                reniec_data = _lookup_reniec_only(dni)
                if reniec_data:
                    return Response(reniec_data)
            return Response(
                {'error': 'no_match', 'message': f'No se encontró cliente con DNI {dni}.'},
                status=404,
            )

        # 2) Lookup por teléfono
        if phone:
            # Normalizar: nos quedamos con últimos 9 dígitos (móvil PE)
            phone_digits = re.sub(r'\D', '', phone)[-9:]
            qs = Clients.objects.filter(
                deleted=False,
            ).extra(
                where=["REPLACE(REPLACE(tel_number, ' ', ''), '+', '') LIKE %s"],
                params=[f'%{phone_digits}'],
            )[:10]
            results = [_serialize_client(c, include_photo=False) for c in qs]
            if len(results) == 1:
                # Re-serializar con foto si es match único
                return Response(_serialize_client(qs[0]))
            if not results:
                return Response(
                    {'error': 'no_match', 'message': f'No se encontró cliente con teléfono {phone}.'},
                    status=404,
                )
            return Response({'matches': results, 'count': len(results)})

        # 3) Lookup por nombre (icontains en first/last)
        if name:
            qs = Clients.objects.filter(
                deleted=False,
            ).filter(
                first_name__icontains=name,
            ) | Clients.objects.filter(
                deleted=False,
                last_name__icontains=name,
            )
            qs = qs.distinct()[:10]
            results = [_serialize_client(c, include_photo=False) for c in qs]
            if len(results) == 1:
                return Response(_serialize_client(list(qs)[0]))
            if not results:
                return Response(
                    {'error': 'no_match', 'message': f'No se encontró cliente con nombre "{name}".'},
                    status=404,
                )
            return Response({'matches': results, 'count': len(results)})

        return Response({'error': 'unhandled'}, status=400)
