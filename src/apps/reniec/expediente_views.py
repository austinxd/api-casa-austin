"""Endpoints REST del expediente extendido por DNI.

Todos bajo /api/v1/reniec/ — admin-only.

    POST /api/v1/reniec/full/<dni>/                    → Orquestador (todos los 7 en paralelo)
         Body opcional: { "force_refresh": true }      → ignora TTLs

    POST /api/v1/reniec/phones/by-number/              → Titular por teléfono
         Body: { "phone": "986607686" }

    GET  /api/v1/reniec/<dni>/family/                  → Árbol + familia-1 (consanguíneos + cohabitantes)
    GET  /api/v1/reniec/<dni>/salaries/                → Sueldos
    GET  /api/v1/reniec/<dni>/marriages/               → Matrimonios
    GET  /api/v1/reniec/<dni>/addresses/               → Direcciones (con is_current_best)
    GET  /api/v1/reniec/<dni>/police/                  → Denuncias policiales

    Cada GET acepta ?refresh=1 para forzar consulta a Leder ignorando TTL.
"""
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .expediente_service import ExpedienteService


def _bool(value) -> bool:
    """Parse '1' / 'true' / 'yes' a True. Cualquier otra cosa a False."""
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'yes', 'y')


def _validate_dni(dni: str):
    if not dni or not str(dni).isdigit() or len(str(dni)) != 8:
        return Response(
            {'error': 'invalid_dni', 'message': 'DNI debe ser 8 dígitos numéricos.'},
            status=400,
        )
    return None


class AdminFullExpedienteView(APIView):
    """POST /api/v1/reniec/full/<dni>/ — Orquestador.

    Body opcional:
        { "force_refresh": true }  → fuerza re-consultar a Leder los 7 endpoints,
                                      ignorando TTL.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.data.get('force_refresh'))
        result = ExpedienteService.get_full_expediente(dni, force_refresh=force)
        if 'error' in result:
            return Response(result, status=400 if result.get('error') == 'invalid_dni' else 500)
        return Response(result)

    def get(self, request, dni: str):
        # Permite también GET para conveniencia (force_refresh por query param)
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh') or request.query_params.get('force'))
        result = ExpedienteService.get_full_expediente(dni, force_refresh=force)
        if 'error' in result:
            return Response(result, status=400 if result.get('error') == 'invalid_dni' else 500)
        return Response(result)


class AdminPhoneByNumberView(APIView):
    """POST /api/v1/reniec/phones/by-number/ — Titular(es) de un número."""
    permission_classes = [IsAdminUser]

    def post(self, request):
        phone = (request.data.get('phone') or '').strip()
        if not phone:
            return Response({'error': 'phone_required'}, status=400)
        result = ExpedienteService.get_phones_by_number(phone)
        return Response(result)


# ─── Sub-endpoints GET (lectura + opcional refresh) ─────────────────────

class AdminFamilyView(APIView):
    """GET /api/v1/reniec/<dni>/family/ — árbol + familia-1 unificados."""
    permission_classes = [IsAdminUser]

    def get(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh'))
        tree = ExpedienteService.get_family_tree(dni, force=force)
        household = ExpedienteService.get_household(dni, force=force)
        return Response({
            'dni': dni,
            'consanguineous': tree.get('relatives', []),
            'household': household.get('relatives', []),
            'count_consanguineous': tree.get('count', 0),
            'count_household': household.get('count', 0),
        })


class AdminSalariesView(APIView):
    """GET /api/v1/reniec/<dni>/salaries/ — sueldos históricos."""
    permission_classes = [IsAdminUser]

    def get(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh'))
        return Response(ExpedienteService.get_salaries(dni, force=force))


class AdminMarriagesView(APIView):
    """GET /api/v1/reniec/<dni>/marriages/ — matrimonios."""
    permission_classes = [IsAdminUser]

    def get(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh'))
        return Response(ExpedienteService.get_marriages(dni, force=force))


class AdminAddressesView(APIView):
    """GET /api/v1/reniec/<dni>/addresses/ — direcciones con dedupe + is_current_best."""
    permission_classes = [IsAdminUser]

    def get(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh'))
        return Response(ExpedienteService.get_addresses(dni, force=force))


class AdminPoliceView(APIView):
    """GET /api/v1/reniec/<dni>/police/ — denuncias policiales clasificadas."""
    permission_classes = [IsAdminUser]

    def get(self, request, dni: str):
        err = _validate_dni(dni)
        if err:
            return err
        force = _bool(request.query_params.get('refresh'))
        return Response(ExpedienteService.get_police_records(dni, force=force))
