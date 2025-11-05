# Casa Austin - Property Reservation API

## Overview
Casa Austin is a Django REST API application designed for managing vacation rental properties. It serves as the backend for Casa Austin's business, handling property reservations, client management, payment processing, and integrating with external services to provide a comprehensive booking experience for multiple vacation homes. The system aims to optimize booking workflows, enhance customer loyalty through a points system, and provide robust management tools for staff. Key capabilities include dynamic pricing, discount management, referral tracking, and advanced analytics for business operations.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **Django 4.2.11** with Django REST Framework.
- **Gunicorn** for production WSGI server.
- **MySQL** for production database, SQLite for development.
- Modular Django app structure.

### Core Applications
- **Clients App**: Client authentication, profiles, loyalty program (points and achievements), referral system.
- **Property App**: Property listings, photos, dynamic pricing, and configurations.
- **Reservation App**: Booking workflows, payment processing, reservation lifecycle, availability search with ERP integration for suggesting options by moving existing reservations.
- **Staff App**: Staff management, automated task assignment, scheduling, time tracking, and workload distribution.
- **Accounts App**: User management and administrative functions.

### UI/UX Decisions
- Django Admin interface for backend management with custom displays for discounts, staff, and referral systems.
- User-friendly display of specific weekday discounts.

### Payment Processing
- Multi-gateway support (MercadoPago, OpenPay).
- Token-based payment validation.
- Voucher upload system for manual payment verification.

### Pricing and Discounts
- Dynamic pricing based on seasons and special dates.
- Automatic discount system with achievement-based triggers and specific weekday selection.
- Discount codes with weekend/weekday restrictions.
- **Base price discount option**: Both manual discount codes and dynamic discount generators support `apply_only_to_base_price` field to apply discounts only to base price (excluding additional guests).
- Late checkout pricing configuration.
- **Referral discount system**: First-time reservation discounts for referred clients, with percentage based on referrer's achievement level (configurable in Django Admin).
- **Dynamic discount code generator** (`DynamicDiscountConfig`): Allows creating automatic discount code configurations with customizable prefix, percentage, validity days, usage limits, base price discount option, and property-specific applicability.
- **Welcome discount system** (Nov 5, 2025): Configurable new user registration incentive with `WelcomeDiscountConfig` model
  * Activatable/deactivatable from Django Admin (only one active config at a time)
  * **Automatic generation**: Codes are generated automatically during user registration if promotion is active
  * Only users registered while benefit is active receive discount code
  * Configurable discount percentage, validity days, minimum amount, and maximum discount
  * Weekday/weekend restrictions available
  * Option to apply only to base price (excluding additional guests)
  * Property-specific applicability
  * **Public status endpoint**: `/api/v1/clients/welcome-discount/status/` (GET, no auth) - Allows frontend to check if promotion is active before registration
  * Registration response includes `welcome_discount` object with code details when promotion is active
  * Manual endpoint available: `/api/v1/clients/client-auth/welcome-discount/` for post-registration requests
  * Client tracking fields: `welcome_discount_issued` and `welcome_discount_issued_at`
  * Validation: Only for new clients without approved reservations
  * Code format: `WELCOME-XXXXXX` (6-character random suffix)

### Authentication and Security
- JWT-based authentication (SimpleJWT).
- CORS handling.
- Environment-based configuration (django-environ).
- API documentation with DRF Spectacular.
- Authentication required for most analytics and client endpoints.

### Analytics and Tracking
- Modular analytics endpoints for search tracking, revenue, and upcoming check-ins.
- Privacy-focused data handling (IP anonymization, partial client name display).
- Referral ranking system with monthly statistics and public access for general stats.
- Event contest system for referral competitions (count and bookings).

### Points System Automation
- **Automatic points assignment**: Daily command `auto_assign_points` processes all reservations with checkout passed
- Command features:
  * Assigns 5% points on effective price (after discount from redeemed points)
  * Assigns referral points to referrer based on configurable percentage
  * Creates Activity Feed entries for both earned and referral points
  * Verifies and assigns achievements automatically
  * `--dry-run` flag for testing without saving changes
- Dual system: Signal for immediate assignment on edits + Daily command for all pending reservations

### File Management
- Image processing (Pillow) for property photos.
- Document handling for vouchers and receipts.

### Technical Implementations
- Implementation of an ERP pricing endpoint for smart availability search.
- Enhanced points system with clearer transaction types and staff adjustment capabilities.
- Bulk import commands for historical data.
- Unified referral statistics API with flexible filtering and detailed client views.
- Event evidence upload system with configurable requirements and admin approval workflow.
- Event slug implementation for SEO-friendly URLs.
- **Event participant name format (Oct 16, 2025)**: Event endpoints now show first name + full first surname (e.g., "Juan Pérez" instead of "Juan P.")
  * Affects: `/api/v1/events/{event_id}/participants/`, `/api/v1/events/{event_id}/winners/`, and contest ranking
  * Consistent formatting across all event-related endpoints
- Referral discount system: Automatic discounts for first-time reservations of referred clients based on referrer's achievement level.
- QR Code reservation endpoint: Public endpoint (`/api/v1/qr/{reservation_id}`) that shows reservation details including client info, Facebook profile, referral code, level (with icon), and referral discount percentage.
- Client info by referral code endpoint: Public endpoint (`/api/v1/clients/by-referral-code/{referral_code}/`) that returns client data (first name, first surname, Facebook profile picture, verification status) and active reservations (only in-progress: from check-in 3 PM to check-out 11 AM server time).
- **Client profile referral discount (Oct 11, 2025)**: `/api/v1/clients/client-auth/profile/` endpoint enhanced to show referral discount information
  * `referred_by_info.has_used_discount`: Indicates if client has made any approved reservation
  * For clients WITHOUT reservations: Shows `discount_percentage` (based on referrer's achievement level) and `discount_available` (true/false)
  * For clients WITH reservations: Shows referrer info only, without discount details (discount already used)
- **Active Reservations Endpoint (Oct 31, 2025)**: Public endpoint `/api/v1/active/` that lists all currently active reservations
  * Time-based validation: Check-in from 12 PM (noon) onwards, check-out until 11 AM (Peru timezone)
  * Returns: reservation ID, property name, property player_id, full client name, referral code, check-in/check-out dates
  * Used for monitoring current guests and music system integration
  * No authentication required (public endpoint)
- **Music System Integration (Oct 30, 2025)**: Migrated to custom Deezer-based API (https://music.casaaustin.pe)
  * **NEW: HTTP-based architecture** replacing WebSocket Music Assistant connection
  * **Deezer streaming**: 320kbps MP3 quality for all houses
  * Player control endpoints (play, pause, stop, next, previous, volume, power, mute)
  * Queue management (view queue, add to queue, remove from queue, clear queue - host only)
  * Music search via Deezer API and charts browsing
  * **Reservation-based sessions**: Each reservation acts as a session (reservation_id = session_id)
  * **Access request system**: Users can request access to control music of an active reservation
  * **Host approval workflow**: Reservation owner (host) accepts/rejects access requests
  * **Time-based validation**: Music control only allowed during active reservation hours (check-in 3 PM, check-out 11 AM)
  * **Security**: Permission system validates that only the host of THE current active reservation or their accepted participants can control music
  * **Player visibility**: Both reservation owners and accepted MusicSessionParticipant users can see and control players
  * **Auto-power management**: Automatic player power control based on active reservations
    - `/auto-power-on/` - Powers on single property player if reservation is active
    - `/auto-power-on-all/` - Powers on all property players with active reservations (public GET endpoint for cron)
  * **Session status messaging**: `/sessions/{reservationId}/participants/` endpoint shows session state
    - **Active sessions**: Returns host info with profile picture and list of accepted participants
    - **Not started**: Shows activation date/time (check-in date at 3 PM) when session hasn't begun (message: "Sesión programada")
    - **Ended**: Shows termination date/time (check-out date at 11 AM) when session has finished (message: "Sesión finalizada")
    - Timezone-aware implementation supporting both USE_TZ=True and USE_TZ=False configurations
  * **DLNA Support**: Music API supports DLNA device discovery and playback
  * **House-based architecture**: Simple house ID system where admins write the house ID directly in Property.player_id field (e.g., "ca1", "ca2", "ca3", "ca4"). This ID is passed directly to the music API without conversion.
  * **Dependencies**: Uses standard `requests` library (no Music Assistant dependencies needed)
  * **Frontend compatibility**: No frontend changes required - same endpoints and responses
  * **Production ready**: Simplified HTTP architecture, no complex WebSocket management needed
- **Contact Synchronization (Nov 2, 2025)**: Script `sync_contacts_nextcloud.py` synchronizes client contacts to Nextcloud via WebDAV
  * **Status indicators with color coding**:
    - 🟡 (Yellow) = Future reservation (upcoming stay)
    - 🟠 (Orange) = Check-in today (all day long on check-in date)
    - 🟢 (Green) = Active stay (intermediate days between check-in and check-out)
    - 🔴 (Red) = Checkout today (all day long on check-out date)
  * **Contact format**: `🐣 Isabel Robalino (250 P) 🟢1️⃣ CA123`
    - Emoji icon = Client's achievement level
    - Points balance displayed
    - Real-time reservation status (yellow/orange/green/red indicator + house number)
    - Referral code shown only when reservation exists
  * **Smart reservation detection**:
    - Check-in day: 🟠 orange all day (even before 12 PM)
    - Intermediate days: 🟢 green (between check-in and check-out)
    - Checkout day: 🔴 red all day (even after 11 AM)
    - Uses `client_id.vcf` naming to prevent duplicates
  * **Sync operations**: Creates, updates, or skips contacts based on changes
  * **WebDAV integration**: Connects to `https://contactos.casaaustin.pe`

## External Dependencies

### Payment Gateways
- **MercadoPago**
- **OpenPay**

### Communication Services
- **Twilio**: SMS and messaging.
- **Telegram Bot API**: Internal notifications and customer communications.
- **WhatsApp Business API**: Customer communication workflows (OTP, payment, cancellations, welcome messages).

### Data and Analytics
- **Google Sheets API**: Via Google Apps Script for data export.
- **ChatGPT Builder API**: For automated discount and promotion management.

### Smart Home Integration
- **Home Assistant**: Property automation and monitoring.

### Authentication
- **Facebook OAuth**: Client verification.

### Third-Party Libraries
- **python-telegram-bot**
- **requests**
- **Pillow**
- **docxtpl**
- **icalendar**
- **babel**
- **django-cors-headers**
- **drf-spectacular**
- **python-slugify**
- **python-dateutil**