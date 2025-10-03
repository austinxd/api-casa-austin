import mysql.connector
import requests
import base64
import unicodedata
import re
from xml.etree import ElementTree as ET
from datetime import date

# =========================
# Config
# =========================
db_config = {
    'host': "localhost",
    'user': "Reservas",
    'password': "!Leonel123",
    'database': "ReservasCA"
}

NEXTCLOUD_URL = "https://contactos.casaaustin.pe/remote.php/dav/addressbooks/users/casaaustin/clientes/"
NEXTCLOUD_USER = "casaaustin"
NEXTCLOUD_PASSWORD = "!Leonel123"

# =========================
# Utilidades
# =========================
def slugify(value: str) -> str:
    value = unicodedata.normalize('NFD', value)
    value = value.encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^a-zA-Z0-9]+', '_', value).strip('_').lower()
    return value

def format_first_word(text: str) -> str:
    """Devuelve solo la primera palabra capitalizada (maneja None/espacios)."""
    if not text:
        return ""
    return text.strip().split()[0].capitalize()

def normalize_phone(phone: str) -> str:
    """Mantiene solo dígitos y '+' inicial si existe. Retorna '' si queda vacío."""
    phone = (phone or "").strip()
    if not phone:
        return ""
    phone = phone.replace(" ", "")
    if phone.startswith('+'):
        digits = re.sub(r'\D', '', phone[1:])
        return ('+' + digits) if digits else ""
    return re.sub(r'\D', '', phone)

def normalize_vcard(text: str) -> str:
    """Normaliza saltos de línea y espacios de fin para comparar vCards."""
    if text is None:
        return ""
    norm = text.replace('\r\n', '\n').replace('\r', '\n')
    norm = '\n'.join(line.rstrip() for line in norm.split('\n')).strip()
    return norm

# =========================
# DB: contactos + icono del NIVEL MÁS ALTO + PUNTOS + RESERVA ACTIVA
# =========================
def read_contacts_from_db():
    """
    Retorna lista de tuplas: (client_id:str, first_name, last_name, tel_number, top_icon, points, has_active_reservation)
    top_icon puede ser '' si no tiene logros.
    points: balance de puntos del cliente.
    has_active_reservation: 1 si tiene al menos una reserva desde hoy en adelante, 0 si no.
    Solo considera contactos con deleted = 0.
    """
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    query = """
        SELECT
            c.id,
            c.first_name,
            c.last_name,
            c.tel_number,
            t.icon AS top_icon,
            COALESCE(c.points_balance, 0) AS points,
            CASE 
                WHEN EXISTS (
                    SELECT 1 
                    FROM reservation_reservation r
                    WHERE r.client_id = c.id
                      AND COALESCE(r.deleted, 0) = 0
                      AND r.status = 'approved'
                      AND r.check_in_date >= CURDATE()
                ) THEN 1
                ELSE 0
            END AS has_active_reservation
        FROM clients_clients c
        LEFT JOIN (
            SELECT
                ca.client_id,
                a.icon,
                ROW_NUMBER() OVER (
                    PARTITION BY ca.client_id
                    ORDER BY
                        a.`order` DESC,
                        a.`required_reservations` DESC,
                        a.`required_referrals` DESC,
                        a.`id` DESC
                ) AS rn
            FROM clients_clientachievement ca
            INNER JOIN clients_achievement a
                ON a.id = ca.achievement_id
        ) AS t
            ON t.client_id = c.id AND t.rn = 1
        WHERE COALESCE(c.deleted, 0) = 0
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    contacts = []
    for client_id, first_name, last_name, tel_number, top_icon, points, has_active_reservation in rows:
        contacts.append((
            str(client_id or "").strip(),    # UUID/string
            first_name or "",
            last_name or "",
            (tel_number or "").strip(),
            top_icon or "",
            float(points or 0),
            int(has_active_reservation or 0)
        ))
    return contacts

# =========================
# vCard
# =========================
def create_vcard(client_id: str, first_name: str, last_name: str, tel_number: str, top_icon: str, points: float, has_active_reservation: int) -> str:
    """
    N: apellido + puntos + indicador; icono + primer nombre → 'Robalino (250 P) 🟢;🐣 Isabel'
    FN: icono + nombre completo + puntos + indicador activo → '🐣 Isabel Robalino (250 P) 🟢'
    UID: estable por client_id (string/UUID)
    """
    given_clean = format_first_word(first_name)
    family_clean = format_first_word(last_name)
    phone = normalize_phone(tel_number)

    if not phone:
        return ""  # omitimos contactos sin teléfono válido

    icon = top_icon if top_icon else "🥚"  # default si no tiene logro

    # Formatear puntos (sin decimales si es número entero)
    points_int = int(points)
    points_str = str(points_int) if points == points_int else f"{points:.2f}"

    # Indicador de reserva activa
    active_indicator = " 🟢" if has_active_reservation else ""

    # Sufijo con puntos e indicador
    suffix = f"({points_str} P){active_indicator}"

    # Nombre con icono al inicio para campo N (solo primer nombre)
    given_with_icon = f"{icon} {given_clean}".strip()
    
    # Apellido con puntos e indicador para campo N
    family_with_suffix = f"{family_clean} {suffix}".strip()
    
    # Nombre completo para display con puntos y indicador
    display_name = f"{icon} {given_clean} {family_clean} {suffix}".strip()

    uid = f"casaustin:{client_id}"

    vcard = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        f"UID:{uid}\n"
        # N: Family;Given;Additional;Prefix;Suffix
        f"N:{family_with_suffix};{given_with_icon};;;\n"
        f"FN:{display_name}\n"
        f"NICKNAME:{display_name}\n"
        f"TEL;TYPE=CELL:{phone}\n"
        "END:VCARD\n"
    )
    return vcard

# =========================
# Nextcloud WebDAV
# =========================
def auth_header():
    token = base64.b64encode(f"{NEXTCLOUD_USER}:{NEXTCLOUD_PASSWORD}".encode()).decode()
    return {'Authorization': f'Basic {token}'}

def list_existing_contacts():
    """Devuelve set con los nombres de archivo .vcf existentes."""
    headers = {**auth_header(), 'Depth': '1'}
    response = requests.request('PROPFIND', NEXTCLOUD_URL, headers=headers)
    if response.status_code != 207:
        print(f"Error listando contactos: {response.status_code} - {response.text}")
        return set()

    files = set()
    try:
        root = ET.fromstring(response.content)
        for resp in root.findall('{DAV:}response'):
            href_el = resp.find('{DAV:}href')
            if href_el is None or not href_el.text:
                continue
            href = href_el.text
            filename = href.rstrip('/').split('/')[-1]
            if filename.lower().endswith('.vcf'):
                files.add(filename)
    except ET.ParseError as e:
        print(f"XML parse error: {e}")
    return files

def fetch_vcard(contact_file: str) -> str:
    url = f"{NEXTCLOUD_URL}{contact_file}"
    r = requests.get(url, headers=auth_header())
    if r.status_code == 200:
        return r.text
    if r.status_code == 404:
        return ""
    print(f"Warning: GET {contact_file} -> {r.status_code}")
    return r.text or ""

def put_vcard(contact_file: str, vcard_text: str) -> bool:
    url = f"{NEXTCLOUD_URL}{contact_file}"
    headers = {
        'Content-Type': 'text/vcard; charset=utf-8',
        **auth_header()
    }
    r = requests.put(url, headers=headers, data=vcard_text.encode('utf-8'))
    if r.status_code in (200, 201, 204):
        return True
    print(f"Error PUT {contact_file}: {r.status_code} - {r.text}")
    return False

# =========================
# Sync (crear/actualizar) usando client_id (string/UUID) como filename
# =========================
def sync_contacts(contacts):
    """
    Archivo: {client_id}.vcf → evita duplicados por cambios de nombre/nivel.
    Crea si no existe. Si existe, compara y actualiza solo si cambió algo.
    Omite contactos sin teléfono (log de aviso).
    """
    existing = list_existing_contacts()
    
    # Contadores
    total = len(contacts)
    created = 0
    updated = 0
    omitted = 0
    unchanged = 0
    errors = 0

    print(f"\n{'='*60}")
    print(f"Iniciando sincronización de {total} contactos...")
    print(f"{'='*60}\n")

    for index, (client_id, first_name, last_name, tel_number, top_icon, points, has_active_reservation) in enumerate(contacts, 1):
        cid = (client_id or "").strip()
        name_display = f"{first_name} {last_name}".strip()
        
        if not cid:
            omitted += 1
            print(f"[{index}/{total}] ❌ OMITIDO - Sin client_id: {name_display}")
            continue

        contact_file = f"{cid}.vcf"
        desired_vcard = create_vcard(cid, first_name, last_name, tel_number, top_icon, points, has_active_reservation)

        if not desired_vcard:
            omitted += 1
            print(f"[{index}/{total}] ❌ OMITIDO - Sin teléfono: {name_display}")
            continue

        desired_norm = normalize_vcard(desired_vcard)

        if contact_file not in existing:
            ok = put_vcard(contact_file, desired_vcard)
            if ok:
                created += 1
                print(f"[{index}/{total}] ✅ CREADO: {name_display}")
            else:
                errors += 1
                print(f"[{index}/{total}] ⚠️  ERROR al crear: {name_display}")
            continue

        current_vcard = fetch_vcard(contact_file)
        current_norm = normalize_vcard(current_vcard)

        if current_norm != desired_norm:
            ok = put_vcard(contact_file, desired_vcard)
            if ok:
                updated += 1
                print(f"[{index}/{total}] 🔄 ACTUALIZADO: {name_display}")
            else:
                errors += 1
                print(f"[{index}/{total}] ⚠️  ERROR al actualizar: {name_display}")
        else:
            unchanged += 1
            # Opcional: comentar esta línea si no quieres ver los sin cambios
            # print(f"[{index}/{total}] ⚪ Sin cambios: {name_display}")
    
    # Resumen final
    print(f"\n{'='*60}")
    print(f"RESUMEN DE SINCRONIZACIÓN")
    print(f"{'='*60}")
    print(f"Total de contactos procesados: {total}")
    print(f"  ✅ Creados:         {created}")
    print(f"  🔄 Actualizados:    {updated}")
    print(f"  ⚪ Sin cambios:     {unchanged}")
    print(f"  ❌ Omitidos:        {omitted}")
    print(f"  ⚠️  Errores:         {errors}")
    print(f"{'='*60}\n")

# =========================
# Main
# =========================
if __name__ == "__main__":
    contacts = read_contacts_from_db()
    sync_contacts(contacts)
