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
- Late checkout pricing configuration.
- **Referral discount system**: First-time reservation discounts for referred clients, with percentage based on referrer's achievement level (configurable in Django Admin).

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
- Referral discount system: Automatic discounts for first-time reservations of referred clients based on referrer's achievement level.
- QR Code reservation endpoint: Public endpoint (`/api/v1/qr/{reservation_id}`) that shows reservation details including client info, Facebook profile, referral code, level (with icon), and referral discount percentage.
- Music Assistant Integration: Complete integration with Music Assistant server for music control in properties. Features include:
  * Player control endpoints (play, pause, stop, next, previous, volume)
  * Queue management (view queue, play media with queue options)
  * Music search and library browsing
  * **Reservation-based sessions**: Each reservation acts as a session (reservation_id = session_id)
  * **Access request system**: Users can request access to control music of an active reservation
  * **Host approval workflow**: Reservation owner (host) accepts/rejects access requests
  * **Time-based validation**: Music control only allowed during active reservation hours (check-in 3 PM, check-out 11 AM)
  * Permission system: only guests with active reservations or accepted participants can control music
  * WebSocket persistent connection to Music Assistant server (wss://music.casaaustin.pe/ws)
  * **NOTA:** Requiere Python 3.11+ (dependencias opcionales: music-assistant-client y music-assistant-models)
  * En Python 3.9/3.10, los endpoints retornan 501 Not Implemented con mensaje informativo

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