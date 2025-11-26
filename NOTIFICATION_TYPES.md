# 📱 Sistema de Notificaciones Push - Casa Austin

Documentación completa de todos los tipos de notificaciones push enviadas a clientes y administradores.

---

## 👤 NOTIFICACIONES PARA CLIENTES

### 1. Reserva Creada
**Trigger:** Cuando se crea una nueva reserva  
**Type:** `reservation_created`

```json
{
  "title": "Reserva Confirmada",
  "body": "Tu reserva en Casa Austin ha sido creada.\nFechas: 15 de diciembre del 2025 al 18 de diciembre del 2025\nHuéspedes: 4 personas\nTotal: $450.00 USD",
  "data": {
    "type": "reservation_created",
    "notification_type": "reservation_created",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "check_in": "2025-12-15",
    "check_out": "2025-12-18",
    "guests": 4,
    "price_usd": "450.00",
    "screen": "ReservationDetail"
  }
}
```

---

### 2. Pago Aprobado
**Trigger:** Cuando se aprueba el pago de una reserva  
**Type:** `payment_approved`

```json
{
  "title": "Pago Aprobado",
  "body": "El pago de tu reserva en Casa Austin ha sido aprobado.\nMonto: $450.00 USD\nCheck-in: 15 de diciembre del 2025\n¡Te esperamos!",
  "data": {
    "type": "payment_approved",
    "notification_type": "payment_approved",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "check_in": "2025-12-15",
    "price_usd": "450.00",
    "screen": "ReservationDetail"
  }
}
```

---

### 3. Pago Pendiente
**Trigger:** Cuando el pago está pendiente  
**Type:** `payment_pending`

```json
{
  "title": "Pago Pendiente",
  "body": "Tu reserva en Casa Austin está pendiente de pago.\nMonto: $450.00 USD\nCheck-in: 15 de diciembre del 2025\nCompleta tu pago para confirmar la reserva.",
  "data": {
    "type": "payment_pending",
    "notification_type": "payment_pending",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "price_usd": "450.00",
    "screen": "ReservationDetail"
  }
}
```

---

### 4. Pago Cancelado
**Trigger:** Cuando se cancela el pago  
**Type:** `payment_cancelled`

```json
{
  "title": "Pago Cancelado",
  "body": "El pago de tu reserva en Casa Austin ha sido cancelado.\nPor favor, contacta con nosotros si necesitas ayuda.",
  "data": {
    "type": "payment_cancelled",
    "notification_type": "payment_cancelled",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "screen": "ReservationDetail"
  }
}
```

---

### 5. Recordatorio de Check-in
**Trigger:** Un día antes del check-in (via comando diario)  
**Type:** `checkin_reminder`

```json
{
  "title": "Recordatorio de Check-in",
  "body": "Mañana es tu check-in en Casa Austin.\nFecha: 15 de diciembre del 2025\nHora de llegada: desde las 3:00 PM\nHuéspedes: 4 personas\n¡Te esperamos!",
  "data": {
    "type": "checkin_reminder",
    "notification_type": "checkin_reminder",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "check_in": "2025-12-15",
    "guests": 4,
    "screen": "ReservationDetail"
  }
}
```

---

### 6. Recordatorio de Check-out
**Trigger:** Un día antes del check-out (via comando diario)  
**Type:** `checkout_reminder`

```json
{
  "title": "Recordatorio de Check-out",
  "body": "Mañana es tu check-out de Casa Austin.\nFecha: 18 de diciembre del 2025\nHora límite: 11:00 AM\nGracias por tu visita. ¡Esperamos verte pronto!",
  "data": {
    "type": "checkout_reminder",
    "notification_type": "checkout_reminder",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "check_out": "2025-12-18",
    "late_checkout": false,
    "screen": "ReservationDetail"
  }
}
```

**Con Late Checkout:**
```json
{
  "late_checkout": true,
  "checkout_time": "1:00 PM"
}
```

---

### 7. Puntos Ganados
**Trigger:** Después del checkout cuando se asignan puntos  
**Type:** `points_earned`

```json
{
  "title": "¡Puntos Ganados!",
  "body": "¡Has ganado 450 puntos por tu reserva en Casa Austin!\nTu balance actual: 1250 puntos\nUsa tus puntos en tu próxima reserva.",
  "data": {
    "type": "points_earned",
    "notification_type": "points_earned",
    "points": "450",
    "balance": "1250",
    "reason": "reserva",
    "screen": "Points"
  }
}
```

---

### 8. Bono por Referido
**Trigger:** Cuando un referido hace una reserva  
**Type:** `referral_bonus`

```json
{
  "title": "¡Bono por Referido!",
  "body": "¡Juan Pérez usó tu código de referido!\nHas ganado 100 puntos de bonificación.\nTu balance actual: 1350 puntos\nSigue compartiendo tu código para ganar más.",
  "data": {
    "type": "referral_bonus",
    "notification_type": "referral_bonus",
    "points": "100",
    "balance": "1350",
    "referred_name": "Juan Pérez",
    "screen": "Points"
  }
}
```

---

### 9. Descuento de Bienvenida
**Trigger:** Al registrarse un nuevo usuario  
**Type:** `welcome_discount`

```json
{
  "title": "¡Bienvenido a Casa Austin!",
  "body": "¡Bienvenido a Casa Austin, Juan!\nTienes un descuento exclusivo del 15% en tu primera reserva.\nCódigo: WELCOME15\nVálido hasta: 31 de diciembre del 2025\n¡Reserva ahora y disfruta!",
  "data": {
    "type": "welcome_discount",
    "notification_type": "welcome_discount",
    "discount_code": "WELCOME15",
    "percentage": "15",
    "valid_until": "2025-12-31",
    "screen": "Home"
  }
}
```

---

### 10. Cambios Múltiples (Consolidado)
**Trigger:** Cuando se modifican varias propiedades a la vez (fechas + precio + huéspedes)  
**Type:** `reservation_updated`

```json
{
  "title": "Reserva Actualizada",
  "body": "Tu reserva en Casa Austin ha sido actualizada:\nFechas: 15 de diciembre del 2025 al 20 de diciembre del 2025\nPrecio: $550.00 USD / S/2,035.00\nHuéspedes: 6 personas",
  "data": {
    "type": "reservation_updated",
    "notification_type": "reservation_updated",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "dates_changed": true,
    "check_in": "2025-12-15",
    "check_out": "2025-12-20",
    "price_changed": true,
    "old_price_usd": "450.00",
    "new_price_usd": "550.00",
    "old_price_pen": "1665.00",
    "new_price_pen": "2035.00",
    "guests_changed": true,
    "old_guests": 4,
    "new_guests": 6,
    "screen": "ReservationDetail"
  }
}
```

**Nota:** Si solo cambia UNA propiedad, usa el tipo específico (`reservation_dates_changed`, `reservation_price_changed`, o `reservation_guests_changed`)

---

### 11. Cambio de Fechas (Solo)
**Trigger:** Cuando solo se modifican las fechas de una reserva  
**Type:** `reservation_dates_changed`

```json
{
  "title": "Fechas Actualizadas",
  "body": "Tu reserva en Casa Austin ha sido actualizada:\nFechas: 15 de diciembre del 2025 al 20 de diciembre del 2025",
  "data": {
    "type": "reservation_dates_changed",
    "notification_type": "reservation_dates_changed",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "dates_changed": true,
    "check_in": "2025-12-15",
    "check_out": "2025-12-20",
    "screen": "ReservationDetail"
  }
}
```

---

### 12. Cambio de Precio (Solo)
**Trigger:** Cuando se modifica el precio de una reserva  
**Type:** `reservation_price_changed`

```json
{
  "title": "Precio Actualizado",
  "body": "El precio de tu reserva en Casa Austin ha sido actualizado.\nNuevo total: $500.00 USD / S/1,850.00",
  "data": {
    "type": "reservation_price_changed",
    "notification_type": "reservation_price_changed",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "old_price_usd": "450.00",
    "new_price_usd": "500.00",
    "old_price_pen": "1665.00",
    "new_price_pen": "1850.00",
    "screen": "ReservationDetail"
  }
}
```

---

### 13. Cambio de Precio (Solo)
**Trigger:** Cuando solo se modifica el precio de una reserva  
**Type:** `reservation_price_changed`

```json
{
  "title": "Precio Actualizado",
  "body": "Tu reserva en Casa Austin ha sido actualizada:\nPrecio: $500.00 USD / S/1,850.00",
  "data": {
    "type": "reservation_price_changed",
    "notification_type": "reservation_price_changed",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "price_changed": true,
    "old_price_usd": "450.00",
    "new_price_usd": "500.00",
    "old_price_pen": "1665.00",
    "new_price_pen": "1850.00",
    "screen": "ReservationDetail"
  }
}
```

---

### 14. Cambio de Huéspedes (Solo)
**Trigger:** Cuando solo cambia el número de huéspedes  
**Type:** `reservation_guests_changed`

```json
{
  "title": "Huéspedes Actualizados",
  "body": "Tu reserva en Casa Austin ha sido actualizada:\nHuéspedes: 6 personas",
  "data": {
    "type": "reservation_guests_changed",
    "notification_type": "reservation_guests_changed",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "guests_changed": true,
    "old_guests": 4,
    "new_guests": 6,
    "screen": "ReservationDetail"
  }
}
```

---

### 15. Reserva Eliminada
**Trigger:** Cuando se elimina/cancela una reserva  
**Type:** `reservation_deleted`

```json
{
  "title": "Reserva Cancelada",
  "body": "Tu reserva en Casa Austin ha sido cancelada.\nFechas: 15 de diciembre del 2025 al 18 de diciembre del 2025\nSi tienes dudas, contáctanos.",
  "data": {
    "type": "reservation_deleted",
    "notification_type": "reservation_deleted",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "check_in": "2025-12-15",
    "check_out": "2025-12-18",
    "price_usd": "450.00",
    "guests": 4,
    "screen": "Reservations"
  }
}
```

---

## 👨‍💼 NOTIFICACIONES PARA ADMINISTRADORES

### 1. Nueva Reserva Creada
**Trigger:** Cuando un cliente crea una reserva  
**Type:** `admin_reservation_created`

```json
{
  "title": "Nueva Reserva Creada",
  "body": "Juan Pérez - Casa Austin\n15 de diciembre del 2025 al 18 de diciembre del 2025 | 4 huéspedes | $450.00 USD",
  "data": {
    "type": "admin_reservation_created",
    "notification_type": "admin_reservation_created",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "client_name": "Juan Pérez",
    "check_in": "2025-12-15",
    "check_out": "2025-12-18",
    "guests": 4,
    "price_usd": "450.00",
    "screen": "AdminReservationDetail"
  }
}
```

---

### 2. Cambio de Estado
**Trigger:** Cuando cambia el estado de una reserva  
**Type:** `admin_status_changed`

```json
{
  "title": "Cambio de Estado: Aprobado",
  "body": "Juan Pérez - Casa Austin\nNuevo estado: Aprobado",
  "data": {
    "type": "admin_status_changed",
    "notification_type": "admin_status_changed",
    "reservation_id": "uuid-123",
    "client_name": "Juan Pérez",
    "property_name": "Casa Austin",
    "old_status": "pending",
    "new_status": "approved",
    "screen": "AdminReservationDetail"
  }
}
```

---

### 3. Cambio de Fechas
**Trigger:** Cuando se modifican las fechas  
**Type:** `admin_dates_changed`

```json
{
  "title": "Cambio de Fechas",
  "body": "Juan Pérez - Casa Austin\nNuevas fechas: 15 de diciembre del 2025 al 20 de diciembre del 2025",
  "data": {
    "type": "admin_dates_changed",
    "notification_type": "admin_dates_changed",
    "reservation_id": "uuid-123",
    "client_name": "Juan Pérez",
    "property_name": "Casa Austin",
    "check_in": "2025-12-15",
    "check_out": "2025-12-20",
    "screen": "AdminReservationDetail"
  }
}
```

---

### 4. Cambio de Precio
**Trigger:** Cuando se modifica el precio  
**Type:** `admin_price_changed`

```json
{
  "title": "Cambio de Precio",
  "body": "Juan Pérez - Casa Austin\nNuevo precio: $500.00 USD / S/1,850.00",
  "data": {
    "type": "admin_price_changed",
    "notification_type": "admin_price_changed",
    "reservation_id": "uuid-123",
    "client_name": "Juan Pérez",
    "property_name": "Casa Austin",
    "old_price_usd": "450.00",
    "new_price_usd": "500.00",
    "old_price_pen": "1665.00",
    "new_price_pen": "1850.00",
    "screen": "AdminReservationDetail"
  }
}
```

---

### 5. Cambio de Huéspedes
**Trigger:** Cuando cambia el número de huéspedes  
**Type:** `admin_guests_changed`

```json
{
  "title": "Cambio de Huéspedes",
  "body": "Juan Pérez - Casa Austin\nNuevo número: 6 personas",
  "data": {
    "type": "admin_guests_changed",
    "notification_type": "admin_guests_changed",
    "reservation_id": "uuid-123",
    "client_name": "Juan Pérez",
    "property_name": "Casa Austin",
    "old_guests": 4,
    "new_guests": 6,
    "screen": "AdminReservationDetail"
  }
}
```

---

### 6. Reserva Eliminada
**Trigger:** Cuando se elimina una reserva  
**Type:** `admin_reservation_deleted`

```json
{
  "title": "Reserva Eliminada",
  "body": "Juan Pérez - Casa Austin\n15 de diciembre del 2025 al 18 de diciembre del 2025 | 4 huéspedes | $450.00 USD",
  "data": {
    "type": "admin_reservation_deleted",
    "notification_type": "admin_reservation_deleted",
    "reservation_id": "uuid-123",
    "property_name": "Casa Austin",
    "client_name": "Juan Pérez",
    "check_in": "2025-12-15",
    "check_out": "2025-12-18",
    "guests": 4,
    "price_usd": "450.00",
    "screen": "AdminReservations"
  }
}
```

---

## 📊 RESUMEN DE TIPOS

### Clientes (14 tipos)
1. `reservation_created` - Nueva reserva
2. `payment_approved` - Pago aprobado
3. `payment_pending` - Pago pendiente
4. `payment_cancelled` - Pago cancelado
5. `checkin_reminder` - Recordatorio check-in
6. `checkout_reminder` - Recordatorio check-out
7. `points_earned` - Puntos ganados
8. `referral_bonus` - Bono por referido
9. `welcome_discount` - Descuento de bienvenida
10. `reservation_updated` - Cambios múltiples consolidados (fechas + precio + huéspedes)
11. `reservation_dates_changed` - Cambio solo de fechas
12. `reservation_price_changed` - Cambio solo de precio
13. `reservation_guests_changed` - Cambio solo de huéspedes
14. `reservation_deleted` - Reserva eliminada

### Administradores (6 tipos)
1. `admin_reservation_created` - Nueva reserva
2. `admin_status_changed` - Cambio de estado
3. `admin_dates_changed` - Cambio de fechas
4. `admin_price_changed` - Cambio de precio
5. `admin_guests_changed` - Cambio de huéspedes
6. `admin_reservation_deleted` - Reserva eliminada

---

## 🔑 CAMPOS COMUNES

Todos los JSONs incluyen:
- `type`: Tipo de acción/evento (identificador único)
- `notification_type`: Mismo que type (para compatibilidad)
- `reservation_id`: UUID de la reserva
- `property_name`: Nombre de la propiedad
- `screen`: Pantalla de destino en la app

Campos específicos según tipo:
- `client_name`: Nombre del cliente (admin only)
- `check_in`: Fecha de entrada
- `check_out`: Fecha de salida
- `guests`: Número de huéspedes
- `price_usd`: Precio en USD
- `price_pen`: Precio en PEN (soles)
- `old_price_usd` / `new_price_usd`: Precio anterior y nuevo en USD
- `old_price_pen` / `new_price_pen`: Precio anterior y nuevo en PEN
- `old_*` / `new_*`: Valores anteriores y nuevos en cambios
- `points`: Puntos ganados
- `balance`: Balance actual de puntos
- `discount_code`: Código de descuento
- `percentage`: Porcentaje de descuento

---

## 💾 ALMACENAMIENTO EN HISTORIAL

Todas estas notificaciones se guardan automáticamente en `NotificationLog` con:
- Título y cuerpo completos
- Datos JSON completos
- Estado de éxito/fallo
- Timestamp de envío
- Estado de lectura
- Token del dispositivo
- Tipo de dispositivo (iOS/Android)

**Acceso al historial:**
- Clientes: `GET /api/v1/clients/push/history/`
- Admins: `GET /api/v1/admin/push/history/`
