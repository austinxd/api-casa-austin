"""Service que consulta los 7 endpoints de Leder y persiste en las tablas
del expediente extendido. Orquesta consultas en paralelo y respeta TTLs.

Métodos:
    get_phones_by_number(phone)        → /telefonia/numero
    get_family_tree(dni)                → /persona/arbol-genealogico
    get_household(dni)                  → /persona/familia-1
    get_salaries(dni)                   → /persona/sueldos
    get_marriages(dni)                  → /persona/matrimonios
    get_addresses(dni)                  → /persona/direcciones
    get_police_records(dni)             → /persona/denuncias-policiales-dni

    get_full_expediente(dni, ...)       → orquestador (los 7 en paralelo)

Cada método:
1. Verifica TTL en PersonExpedienteMeta. Si está fresco, devuelve de cache.
2. Si no, consulta Leder vía LederHTTP.
3. Persiste resultado en su tabla (idempotente por unique_together).
4. Marca meta.mark_fetched(field).
5. Devuelve datos formateados.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DNICache
from .service import ReniecService
from .expediente_models import (
    PersonAddress,
    PersonExpedienteMeta,
    PersonFamilyRelation,
    PersonMarriage,
    PersonPhone,
    PersonPoliceRecord,
    PersonSalaryRecord,
)
from .expediente_helpers import (
    classify_tipificacion,
    normalize_address,
    normalize_phone,
    parse_datetime_leder,
    parse_period,
)

logger = logging.getLogger(__name__)

# ─── HTTP base ───────────────────────────────────────────────────────────

LEDER_BASE_URL = getattr(settings, 'RENIEC_API_URL', '').rsplit('/persona/', 1)[0]
# Si no se pudo derivar (porque RENIEC_API_URL apunta directo a /persona/reniec)
if not LEDER_BASE_URL or LEDER_BASE_URL.endswith('reniec'):
    LEDER_BASE_URL = 'https://leder-data-api.ngrok.dev/v1.7'


def _leder_post(endpoint: str, payload: Dict[str, Any], timeout: int = 30) -> Optional[Dict]:
    """POST genérico a Leder. Devuelve `result` dict, o None si error/empty."""
    token = getattr(settings, 'RENIEC_API_TOKEN', '')
    if not token:
        logger.error("RENIEC_API_TOKEN no configurado")
        return None
    url = f"{LEDER_BASE_URL}{endpoint}"
    body = {**payload, "token": token}
    try:
        resp = requests.post(
            url, json=body,
            headers={'Content-Type': 'application/json'},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.warning(f"Leder {endpoint} error de red: {e}")
        return None
    if resp.status_code != 200:
        logger.warning(f"Leder {endpoint} HTTP {resp.status_code}: {resp.text[:300]}")
        return None
    try:
        data = resp.json()
    except ValueError:
        logger.warning(f"Leder {endpoint} JSON inválido")
        return None
    # Leder responde "not found data" como mensaje cuando result={}
    if data.get('message') == 'not found data':
        return None
    return data.get('result') or None


# ─── Helper: meta + lazy DNICache de familiares ──────────────────────────

def _get_or_create_meta(dni_obj: DNICache) -> PersonExpedienteMeta:
    meta, _ = PersonExpedienteMeta.objects.get_or_create(dni=dni_obj)
    return meta


def _calc_age(birthday) -> Optional[int]:
    if not birthday:
        return None
    from datetime import date as _date
    today = _date.today()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def serialize_person(d: DNICache) -> Dict[str, Any]:
    """Serializa un DNICache a una estructura categorizada con campos
    nombrados para consumo del frontend. NO devuelve raw_data — sólo los
    campos que se interpretan.
    """
    fmt_date = lambda x: x.isoformat() if x else None

    return {
        'dni': d.dni,
        # ── Identidad básica ──
        'identidad': {
            'nombres': d.nombres or '',
            'apellido_paterno': d.apellido_paterno or '',
            'apellido_materno': d.apellido_materno or '',
            'apellido_casada': d.apellido_casada or '',
            'nombre_completo': f"{d.nombres or ''} {d.apellido_paterno or ''} {d.apellido_materno or ''}".strip(),
            'sexo': d.sexo or '',
            'sexo_label': {'M': 'Masculino', 'F': 'Femenino'}.get((d.sexo or '').upper(), d.sexo or ''),
            'fecha_nacimiento': fmt_date(d.fecha_nacimiento),
            'edad': _calc_age(d.fecha_nacimiento),
            'estado_civil': d.estado_civil or '',
            'grado_instruccion': d.grado_instruccion or '',
            'estatura_cm': d.estatura,
        },
        # ── Documento ──
        'documento': {
            'nu_dni': d.nu_dni or d.dni,
            'nu_ficha': d.nu_ficha or '',
            'nu_imagen': d.nu_imagen or '',
            'digito_verificacion': d.digito_verificacion or '',
            'fecha_emision': fmt_date(d.fecha_emision),
            'fecha_inscripcion': fmt_date(d.fecha_inscripcion),
            'fecha_caducidad': fmt_date(d.fecha_caducidad),
            'esta_vigente': bool(d.fecha_caducidad and d.fecha_caducidad >= timezone.now().date()) if d.fecha_caducidad else None,
        },
        # ── Filiación (padres) ──
        'filiacion': {
            'nombre_padre': d.nom_padre or '',
            'nombre_madre': d.nom_madre or '',
        },
        # ── Lugar de nacimiento ──
        'lugar_nacimiento': {
            'pais': d.pais or '',
            'departamento': d.departamento or '',
            'provincia': d.provincia or '',
            'distrito': d.distrito or '',
        },
        # ── Dirección actual según RENIEC ──
        'direccion_reniec': {
            'pais': d.pais_direccion or '',
            'departamento': d.departamento_direccion or '',
            'provincia': d.provincia_direccion or '',
            'distrito': d.distrito_direccion or '',
            'direccion_completa': d.direccion or '',
            'ubigeo_reniec': d.ubigeo_reniec or '',
            'ubigeo_inei': d.ubigeo_inei or '',
            'codigo_postal': d.codigo_postal or '',
        },
        # ── Contacto (lo que tiene Reniec, no es definitivo) ──
        'contacto': {
            'telefono': d.telefono or '',
            'email': d.email or '',
        },
        # ── Datos electorales / restricciones ──
        'electoral': {
            'grupo_votacion': d.gp_votacion or '',
            'multas_electorales': d.multas_electorales or '',
            'multa_administrativa': d.multa_admin or '',
        },
        'restricciones': {
            'observacion': d.observacion or '',
            'cancelacion': d.cancelacion or '',
            'fecha_restriccion': d.fecha_restriccion or '',
            'descripcion_restriccion': d.de_restriccion or '',
        },
        # ── Fallecimiento (si aplica) ──
        'fallecimiento': {
            'fecha': fmt_date(d.fecha_fallecimiento) if d.fecha_fallecimiento else None,
            'departamento': d.depa_fallecimiento or '',
            'provincia': d.prov_fallecimiento or '',
            'distrito': d.dist_fallecimiento or '',
            'fallecido': bool(d.fecha_fallecimiento),
        },
        # ── Otros ──
        'otros': {
            'dona_organos': d.dona_organos or '',
            'fecha_actualizacion': fmt_date(d.fecha_actualizacion),
        },
        # ── Imágenes (base64) ──
        'imagenes': {
            'foto_b64': d.foto or '',
            'firma_b64': d.firma or '',
            'huella_izquierda_b64': d.huella_izquierda or '',
            'huella_derecha_b64': d.huella_derecha or '',
        },
    }


def _ensure_dni_cache(dni: str, fallback_name: str = '') -> Optional[DNICache]:
    """Si no existe DNICache para `dni`, lo crea con info mínima y dispara
    un lookup completo en background para enriquecerlo con foto/firma/etc.
    Si ya existe, lo devuelve.

    Returns: DNICache o None si dni inválido.
    """
    if not dni or not str(dni).isdigit() or len(str(dni)) != 8:
        return None
    cached = DNICache.get_or_none(dni)
    if cached:
        return cached
    # Crear mínimo
    cached = DNICache.objects.create(
        dni=dni,
        nombres=(fallback_name or '').strip().upper()[:200],
        source='lazy_pending',
    )
    # Lookup completo en background — fire and forget
    def _background_enrich():
        try:
            ReniecService.lookup(
                dni=dni,
                source_app='lazy_family_enrich',
                include_photo=True,
                include_full_data=True,
            )
        except Exception as e:
            logger.warning(f"Lazy enrich falló para DNI {dni}: {e}")
    t = threading.Thread(target=_background_enrich, daemon=True)
    t.start()
    return cached


# ─── ExpedienteService ───────────────────────────────────────────────────

class ExpedienteService:

    # ──── 1) Telefonía ───────────────────────────────────────────────────
    @classmethod
    def get_phones_by_number(cls, phone: str) -> Dict[str, Any]:
        """Busca el titular de un teléfono según Leder.

        Persiste los hallazgos en PersonPhone (1 row por (phone, operator, dni)).
        Si el número aparece con varios operadores, guarda todos.
        Si la misma combinación ya existe, actualiza period/plan/source.
        """
        phone_n = normalize_phone(phone)
        if not phone_n:
            return {'error': 'phone_required', 'phone': phone}

        result = _leder_post('/telefonia/numero', {'numero': phone_n})
        if not result:
            return {'phone': phone_n, 'titulares': [], 'message': 'no_data'}

        coincidences = result.get('coincidences') or []
        saved = []
        for c in coincidences:
            doc = c.get('documento')
            if not doc:
                continue
            # Asegurar DNICache (lazy si no existe)
            dni_obj = _ensure_dni_cache(doc)
            if not dni_obj:
                continue
            obj, created = PersonPhone.objects.update_or_create(
                phone=phone_n,
                operator=(c.get('fuente') or '').strip(),
                dni=dni_obj,
                defaults={
                    'plan': (c.get('plan') or '').strip()[:100],
                    'period': parse_period(c.get('periodo')),
                    'source': (c.get('fuente') or '').strip()[:50],
                },
            )
            saved.append({
                'dni': doc,
                'operator': obj.operator,
                'plan': obj.plan,
                'period': obj.period.isoformat() if obj.period else None,
                'created': created,
            })
        return {'phone': phone_n, 'count': len(saved), 'titulares': saved}

    # ──── 2) Árbol genealógico ───────────────────────────────────────────
    @classmethod
    def get_family_tree(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('family_tree'):
            return cls._family_tree_from_cache(dni_obj, source='arbol_genealogico')

        result = _leder_post('/persona/arbol-genealogico', {'dni': dni})
        if not result:
            meta.mark_fetched('family_tree')
            return cls._family_tree_from_cache(dni_obj, source='arbol_genealogico')

        for c in (result.get('coincidences') or []):
            rdni = c.get('dni')
            if not rdni:
                continue
            full_name = f"{c.get('ap','')} {c.get('am','')} {c.get('nom','')}".strip()
            relative_obj = _ensure_dni_cache(rdni, fallback_name=full_name)
            if not relative_obj:
                continue
            PersonFamilyRelation.objects.update_or_create(
                dni=dni_obj,
                relative_dni=relative_obj,
                source=PersonFamilyRelation.RelationSource.ARBOL,
                defaults={
                    'relation_type': (c.get('tipo') or '').strip()[:40],
                    'verification': (c.get('verificacion_relacion') or '')[:15],
                    'cached_name': full_name[:200],
                    'cached_gender': (c.get('ge') or '')[:15],
                    'cached_age_at_query': c.get('edad'),
                },
            )
        meta.mark_fetched('family_tree')
        return cls._family_tree_from_cache(dni_obj, source='arbol_genealogico')

    @classmethod
    def get_household(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('family_household'):
            return cls._family_tree_from_cache(dni_obj, source='familia_1')

        result = _leder_post('/persona/familia-1', {'dni': dni})
        if not result:
            meta.mark_fetched('family_household')
            return cls._family_tree_from_cache(dni_obj, source='familia_1')

        familiares = (result.get('general') or {}).get('familiares') or {}
        for c in (familiares.get('coincidences') or []):
            rdni = c.get('nro_documento')
            if not rdni:
                continue
            full_name = f"{c.get('ape_pat','')} {c.get('ape_mat','')} {c.get('nombres','')}".strip()
            relative_obj = _ensure_dni_cache(rdni, fallback_name=full_name)
            if not relative_obj:
                continue
            birthday = None
            if c.get('fecha_nac'):
                birthday = parse_period(c['fecha_nac'])
            PersonFamilyRelation.objects.update_or_create(
                dni=dni_obj,
                relative_dni=relative_obj,
                source=PersonFamilyRelation.RelationSource.FAMILIA,
                defaults={
                    'relation_type': 'COHABITANTE',
                    'cached_name': full_name[:200],
                    'cached_gender': (c.get('genero') or '')[:15],
                    'cached_age_at_query': c.get('edad'),
                    'cached_birthday': birthday,
                },
            )
        meta.mark_fetched('family_household')
        return cls._family_tree_from_cache(dni_obj, source='familia_1')

    @classmethod
    def _family_tree_from_cache(cls, dni_obj, source) -> Dict[str, Any]:
        rows = PersonFamilyRelation.objects.filter(
            dni=dni_obj, source=source, deleted=False,
        ).select_related('relative_dni').order_by('relation_type')
        return {
            'dni': dni_obj.dni,
            'source': source,
            'count': rows.count(),
            'relatives': [{
                'dni': r.relative_dni_id,
                'name': r.cached_name,
                'gender': r.cached_gender,
                'age': r.cached_age_at_query,
                'relation_type': r.relation_type,
                'verification': r.verification,
            } for r in rows],
        }

    # ──── 3) Sueldos ──────────────────────────────────────────────────────
    @classmethod
    def get_salaries(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('salaries'):
            return cls._salaries_from_cache(dni_obj)

        result = _leder_post('/persona/sueldos', {'dni': dni})
        if not result:
            meta.mark_fetched('salaries')
            return cls._salaries_from_cache(dni_obj)

        for c in (result.get('coincidences') or []):
            period = parse_period(c.get('periodo'))
            if not period:
                continue
            try:
                salary = float(str(c.get('sueldo') or '0').replace(',', '.'))
            except (ValueError, TypeError):
                salary = None
            PersonSalaryRecord.objects.update_or_create(
                dni=dni_obj,
                ruc=(c.get('ruc') or '')[:11],
                period=period,
                defaults={
                    'company_name': (c.get('empresa') or '')[:255],
                    'situation': (c.get('situacion') or '')[:2],
                    'salary_pen': salary,
                },
            )
        meta.mark_fetched('salaries')
        return cls._salaries_from_cache(dni_obj)

    @classmethod
    def _salaries_from_cache(cls, dni_obj) -> Dict[str, Any]:
        rows = PersonSalaryRecord.objects.filter(
            dni=dni_obj, deleted=False,
        ).order_by('-period')[:200]
        return {
            'dni': dni_obj.dni,
            'count': PersonSalaryRecord.objects.filter(dni=dni_obj, deleted=False).count(),
            'records': [{
                'ruc': r.ruc, 'company': r.company_name,
                'situation': r.situation, 'salary_pen': float(r.salary_pen) if r.salary_pen else None,
                'period': r.period.isoformat() if r.period else None,
            } for r in rows],
        }

    # ──── 4) Matrimonios ──────────────────────────────────────────────────
    @classmethod
    def get_marriages(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('marriages'):
            return cls._marriages_from_cache(dni_obj)

        result = _leder_post('/persona/matrimonios', {'dni': dni})
        # result puede ser None (no casado) — eso es válido
        if result:
            # El shape exacto puede variar. Guardamos lo que venga en source_raw.
            spouse_dni_val = result.get('dni_conyuge') or result.get('spouse_dni')
            spouse_obj = _ensure_dni_cache(spouse_dni_val) if spouse_dni_val else None
            PersonMarriage.objects.update_or_create(
                dni=dni_obj,
                spouse_dni=spouse_obj,
                defaults={
                    'spouse_name': (result.get('nombre_conyuge') or result.get('spouse_name') or '')[:200],
                    'marriage_date': parse_period(result.get('fecha_matrimonio') or result.get('marriage_date')),
                    'divorce_date': parse_period(result.get('fecha_divorcio') or result.get('divorce_date')),
                    'location': (result.get('lugar') or result.get('location') or '')[:200],
                    'source_raw': result,
                },
            )
        meta.mark_fetched('marriages')
        return cls._marriages_from_cache(dni_obj)

    @classmethod
    def _marriages_from_cache(cls, dni_obj) -> Dict[str, Any]:
        rows = PersonMarriage.objects.filter(dni=dni_obj, deleted=False)
        return {
            'dni': dni_obj.dni,
            'count': rows.count(),
            'marriages': [{
                'spouse_dni': r.spouse_dni_id, 'spouse_name': r.spouse_name,
                'marriage_date': r.marriage_date.isoformat() if r.marriage_date else None,
                'divorce_date': r.divorce_date.isoformat() if r.divorce_date else None,
                'location': r.location,
            } for r in rows],
        }

    # ──── 5) Direcciones ──────────────────────────────────────────────────
    @classmethod
    def get_addresses(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('addresses'):
            return cls._addresses_from_cache(dni_obj)

        result = _leder_post('/persona/direcciones', {'dni': dni})
        if not result:
            meta.mark_fetched('addresses')
            return cls._addresses_from_cache(dni_obj)

        now = timezone.now().date()
        for c in (result.get('coincidences') or []):
            raw = (c.get('direccion') or '').strip()
            if not raw:
                continue
            norm = normalize_address(raw)
            ubicacion = (c.get('ubicacion') or '')[:200]
            source = (c.get('fuente') or '')[:50]
            obj, created = PersonAddress.objects.get_or_create(
                dni=dni_obj, address_norm=norm,
                defaults={
                    'address_raw': raw[:500],
                    'ubicacion': ubicacion,
                    'source': source,
                    'first_seen': now,
                    'last_seen': now,
                },
            )
            if not created:
                # ya existía — actualizar last_seen y posiblemente source si es más reciente
                obj.last_seen = now
                if source and (not obj.source or 'RENIEC' in source):
                    obj.source = source
                    obj.source_year = None  # forzar recompute en save()
                obj.save(update_fields=['last_seen', 'source', 'source_year', 'updated'])

        # Calcular is_current_best (la más reciente por source_year)
        cls._compute_current_best_address(dni_obj)

        meta.mark_fetched('addresses')
        return cls._addresses_from_cache(dni_obj)

    @classmethod
    def _compute_current_best_address(cls, dni_obj):
        """Marca 1 sola PersonAddress como `is_current_best=True` por persona.
        Criterio: source_year más reciente. Si empate, last_seen más reciente.
        """
        addrs = list(PersonAddress.objects.filter(dni=dni_obj, deleted=False))
        if not addrs:
            return
        addrs.sort(key=lambda a: (a.source_year or 0, a.last_seen), reverse=True)
        for i, a in enumerate(addrs):
            should_be_best = (i == 0)
            if a.is_current_best != should_be_best:
                a.is_current_best = should_be_best
                a.save(update_fields=['is_current_best', 'updated'])

    @classmethod
    def _addresses_from_cache(cls, dni_obj) -> Dict[str, Any]:
        rows = PersonAddress.objects.filter(
            dni=dni_obj, deleted=False,
        ).order_by('-is_current_best', '-source_year', '-last_seen')
        return {
            'dni': dni_obj.dni,
            'count': rows.count(),
            'addresses': [{
                'address': r.address_raw, 'normalized': r.address_norm,
                'ubicacion': r.ubicacion, 'source': r.source,
                'source_year': r.source_year, 'last_seen': r.last_seen.isoformat(),
                'is_current_best': r.is_current_best,
            } for r in rows],
        }

    # ──── 6) Denuncias policiales ────────────────────────────────────────
    @classmethod
    def get_police_records(cls, dni: str, force: bool = False) -> Dict[str, Any]:
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni'}
        meta = _get_or_create_meta(dni_obj)
        if not force and not meta.needs_refresh('police'):
            return cls._police_from_cache(dni_obj)

        result = _leder_post('/persona/denuncias-policiales-dni', {'dni': dni})
        if not result:
            meta.mark_fetched('police')
            return cls._police_from_cache(dni_obj)

        for c in (result.get('coincidences') or []):
            general = c.get('general') or {}
            nro = general.get('nro_denuncia')
            if not nro:
                continue
            tipificacion_raw = ' / '.join(general.get('tipificacion') or [])
            contenido = '\n'.join(general.get('contenido') or []) if isinstance(general.get('contenido'), list) else (general.get('contenido') or '')

            # Determinar rol_dni: buscar el DNI consultado en personas[]
            personas = c.get('personas') or []
            rol_dni = 'DESCONOCIDO'
            for persona in personas:
                doc_text = persona.get('documento') or ''
                # 'DOCUMENTO DE IDENTIDAD DNI : 45816846' o variantes
                if dni in str(doc_text):
                    situacion = (persona.get('situacion') or '').upper().strip()
                    # Mapear a nuestros choices
                    if situacion in ('DENUNCIANTE', 'DENUNCIADO', 'AGRAVIADO',
                                      'TESTIGO', 'INVESTIGADO', 'IMPUTADO'):
                        rol_dni = situacion
                    elif situacion:
                        rol_dni = 'OTRO'
                    break
            # Fallback: si no se encontró en personas[], usar general.tipo_denunciante
            # (suele indicar el rol principal del caso)
            if rol_dni == 'DESCONOCIDO':
                tipo_d = (general.get('tipo_denunciante') or '').upper().strip()
                if tipo_d in ('DENUNCIANTE', 'DENUNCIADO', 'AGRAVIADO'):
                    rol_dni = tipo_d

            PersonPoliceRecord.objects.update_or_create(
                dni=dni_obj,
                nro_denuncia=str(nro)[:30],
                defaults={
                    'clave': (general.get('clave') or '')[:30],
                    'codigo_ruva': (general.get('codigo_ruva') or '')[:30] if general.get('codigo_ruva') else '',
                    'region_policial': (general.get('region_policial') or '')[:100],
                    'comisaria': (general.get('comisaria') or '')[:100],
                    'denuncia_type': (general.get('tipo') or '')[:30],
                    'formalidad': (general.get('formalidad') or '')[:30],
                    'condicion': (general.get('condicion') or '')[:200],
                    'tipificacion_raw': tipificacion_raw,
                    'category': classify_tipificacion(tipificacion_raw),
                    'rol_dni': rol_dni,
                    'nombre_denunciante': (general.get('nombre_denunciante') or '')[:200],
                    'personas_raw': personas,
                    'fecha_hecho': parse_datetime_leder(general.get('fecha_hora_hecho')),
                    'fecha_registro': parse_datetime_leder(general.get('fecha_hora_registro')),
                    'lugar_hecho': (general.get('lugar_hecho') or '')[:300],
                    'contenido': contenido,
                    'qr_valor': (general.get('qr_valor') or '')[:255],
                },
            )
        meta.mark_fetched('police')
        return cls._police_from_cache(dni_obj)

    @classmethod
    def _police_from_cache(cls, dni_obj) -> Dict[str, Any]:
        from django.db.models import Count
        rows = PersonPoliceRecord.objects.filter(
            dni=dni_obj, deleted=False,
        ).order_by('-fecha_hecho')
        by_cat = dict(
            rows.values_list('category').annotate(n=Count('id')).values_list('category', 'n')
        )
        return {
            'dni': dni_obj.dni,
            'count': rows.count(),
            'by_category': by_cat,
            'records': [{
                'nro_denuncia': r.nro_denuncia, 'category': r.category,
                'rol_dni': r.rol_dni,
                'nombre_denunciante': r.nombre_denunciante,
                'personas': r.personas_raw,
                'comisaria': r.comisaria, 'denuncia_type': r.denuncia_type,
                'formalidad': r.formalidad, 'tipificacion': r.tipificacion_raw,
                'fecha_hecho': r.fecha_hecho.isoformat() if r.fecha_hecho else None,
                'lugar_hecho': r.lugar_hecho, 'contenido': r.contenido,
            } for r in rows],
        }

    # ──── 7) Orquestador /full/ ──────────────────────────────────────────
    @classmethod
    def get_full_expediente(cls, dni: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Ejecuta los 7 endpoints (excepto phones que es por número) en paralelo.

        Phones NO se incluye aquí porque ese se busca al revés (por número, no
        por DNI). Para el expediente listamos los que ya hayan sido guardados
        para este DNI.
        """
        dni_obj = _ensure_dni_cache(dni)
        if not dni_obj:
            return {'error': 'invalid_dni', 'dni': dni}

        # Si no tiene datos básicos en DNICache, hacer lookup primero
        if not dni_obj.nombres or dni_obj.source == 'lazy_pending':
            try:
                ReniecService.lookup(
                    dni=dni,
                    source_app='expediente_full',
                    include_photo=True,
                    include_full_data=True,
                )
                dni_obj.refresh_from_db()
            except Exception as e:
                logger.warning(f"Lookup principal falló para {dni}: {e}")

        meta = _get_or_create_meta(dni_obj)

        # Decidir qué endpoints refrescar
        tasks = {}
        if force_refresh or meta.needs_refresh('family_tree'):
            tasks['family_tree'] = lambda: cls.get_family_tree(dni, force=True)
        if force_refresh or meta.needs_refresh('family_household'):
            tasks['family_household'] = lambda: cls.get_household(dni, force=True)
        if force_refresh or meta.needs_refresh('salaries'):
            tasks['salaries'] = lambda: cls.get_salaries(dni, force=True)
        if force_refresh or meta.needs_refresh('marriages'):
            tasks['marriages'] = lambda: cls.get_marriages(dni, force=True)
        if force_refresh or meta.needs_refresh('addresses'):
            tasks['addresses'] = lambda: cls.get_addresses(dni, force=True)
        if force_refresh or meta.needs_refresh('police'):
            tasks['police'] = lambda: cls.get_police_records(dni, force=True)

        # Ejecutar en paralelo (max 6 workers — uno por endpoint)
        results = {}
        if tasks:
            with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                future_map = {ex.submit(fn): name for name, fn in tasks.items()}
                for future in as_completed(future_map):
                    name = future_map[future]
                    try:
                        results[name] = future.result()
                    except Exception as e:
                        logger.exception(f"Error en endpoint {name} para {dni}")
                        results[name] = {'error': str(e)}

        meta.last_full_refresh_at = timezone.now()
        meta.save(update_fields=['last_full_refresh_at', 'updated'])

        # Refrescar datos básicos desde DB (puede que el lookup principal arriba los haya actualizado)
        dni_obj.refresh_from_db()

        return {
            'dni': dni_obj.dni,
            # Persona con campos categorizados (NO raw_data)
            'person': serialize_person(dni_obj),
            'family': {
                'consanguineous': cls._family_tree_from_cache(dni_obj, 'arbol_genealogico')['relatives'],
                'household': cls._family_tree_from_cache(dni_obj, 'familia_1')['relatives'],
            },
            'salaries': cls._salaries_from_cache(dni_obj),
            'marriages': cls._marriages_from_cache(dni_obj),
            'addresses': cls._addresses_from_cache(dni_obj),
            'police_records': cls._police_from_cache(dni_obj),
            'meta': {
                'last_full_refresh_at': meta.last_full_refresh_at.isoformat() if meta.last_full_refresh_at else None,
                'family_tree_fetched_at': meta.family_tree_fetched_at.isoformat() if meta.family_tree_fetched_at else None,
                'family_household_fetched_at': meta.family_household_fetched_at.isoformat() if meta.family_household_fetched_at else None,
                'salaries_fetched_at': meta.salaries_fetched_at.isoformat() if meta.salaries_fetched_at else None,
                'marriages_fetched_at': meta.marriages_fetched_at.isoformat() if meta.marriages_fetched_at else None,
                'addresses_fetched_at': meta.addresses_fetched_at.isoformat() if meta.addresses_fetched_at else None,
                'police_fetched_at': meta.police_fetched_at.isoformat() if meta.police_fetched_at else None,
                'refreshed_this_call': list(tasks.keys()),
            },
        }
