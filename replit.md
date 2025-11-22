# Casa Austin - Property Reservation API

## Overview
Casa Austin is a Django REST API application for managing vacation rental properties. It handles property reservations, client management, payment processing, and integrates with external services to provide a comprehensive booking experience. The system optimizes booking workflows, enhances customer loyalty through a points system, and offers robust management tools, including dynamic pricing, discount management, referral tracking, and advanced analytics.

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
  * **Enhancement (Nov 22, 2025)**: Property list endpoint (`/api/v1/property/`) now includes `exchange_rate` field at the top level of the response, showing the current USD to SOL conversion rate.
- **Reservation App**: Booking workflows, payment processing, reservation lifecycle, availability search with ERP integration.
- **Staff App**: Staff management, task assignment, scheduling, time tracking.
- **Accounts App**: User management and administrative functions.

### UI/UX Decisions
- Django Admin interface for backend management with custom displays.
- User-friendly display of specific weekday discounts.

### Payment Processing
- Multi-gateway support (MercadoPago, OpenPay).
- Token-based payment validation.
- Voucher upload system for manual payment verification.

### Pricing and Discounts
- Dynamic pricing based on seasons and special dates.
- Automatic discount system with achievement-based triggers and specific weekday selection.
- Discount codes with weekend/weekday restrictions and an option to apply only to the base price.
  * **Bug fix (Nov 7, 2025)**: Fixed validation of weekday/weekend restrictions to check against check-in date instead of current date
  * Improved error messages to clearly indicate "El check-in seleccionado cae en {día}" instead of "Hoy es {día}"
  * Validation now properly checks the day of the week of the reservation's check-in date, not today's date
  * **Behavior change (Nov 14, 2025)**: When discount code is invalid (wrong day, expired, etc), reservations now proceed WITHOUT the discount instead of failing completely
- Late checkout pricing configuration.
- Referral discount system for first-time reservations based on referrer's achievement level.
- Dynamic discount code generator with customizable prefixes, percentages, validity, and usage limits.
- Configurable welcome discount system for new user registrations, with automatic code generation, public status endpoint, and specific weekday selection.
  * **Feature added (Nov 14, 2025)**: Welcome discount configuration now supports specific weekday selection (same as automatic discounts), with priority over generic weekday/weekend restrictions.

### Authentication and Security
- JWT-based authentication (SimpleJWT).
- CORS handling.
- Environment-based configuration (django-environ).
- API documentation with DRF Spectacular.

### Analytics and Tracking
- Modular analytics endpoints for search tracking, revenue, and upcoming check-ins.
- Privacy-focused data handling.
- Referral ranking system with monthly statistics and public access.
- Event contest system for referral competitions.

### Points System Automation
- Automatic points assignment for reservations after checkout.
- Referral points assignment to referrer.
- Automatic achievement assignment.
- Activity Feed entries for points.

### File Management
- Image processing (Pillow) for property photos.
- Document handling for vouchers and receipts.

### Technical Implementations
- ERP pricing endpoint integration for smart availability search.
  * **Bug fix (Nov 14, 2025)**: Fixed availability check to include 'under_review' status - reservations in review no longer show properties as available
- Enhanced points system with clearer transaction types and staff adjustment capabilities.
- Bulk import commands for historical data.
- Unified referral statistics API with flexible filtering.
- Event evidence upload system with admin approval.
- Event slug implementation for SEO-friendly URLs.
- Consistent participant name formatting across event endpoints.
- QR Code reservation endpoint displaying client info, referral code, and discount.
- Client info by referral code endpoint showing client data and active reservations.
- Client profile endpoint enhanced to show referral discount information.
- Public endpoint `/api/v1/active/` for listing currently active reservations with guest count and check-in information.
  * **Enhancement (Nov 20, 2025)**: Added `guests` field to show number of people in each active reservation.
  * **Enhancement (Nov 20, 2025)**: Added `check_in_today` field to list all reservations checking in today.
  * **Enhancement (Nov 21, 2025)**: Added `temperature_pool`, `late_checkout`, and `comentarios` fields to show pool heating status, late checkout status, and user comments.
  * **Enhancement (Nov 21, 2025)**: Added `phone` field to display client's phone number in both active reservations and check-in today arrays.
- Reservations API filter `created_today=true` to list only reservations created on the current date.
  * **Bug fix (Nov 7, 2025)**: Fixed filter to use UTC boundary ranges instead of `__date` lookup to avoid MySQL CONVERT_TZ issues when timezone tables are missing.
- Music System Integration migrated to a custom Deezer-based HTTP API for streaming and player control, with reservation-based sessions, host approval workflow for access requests, time-based validation, and auto-power management for players. Supports DLNA.
- Contact Synchronization script (`sync_contacts_nextcloud.py`) to Nextcloud via WebDAV, showing real-time reservation status with color-coded indicators, client points, and referral codes.

## External Dependencies

### Payment Gateways
- **MercadoPago**
- **OpenPay**

### Communication Services
- **Twilio**
- **Telegram Bot API**
- **WhatsApp Business API**

### Data and Analytics
- **Google Sheets API**
- **ChatGPT Builder API**

### Smart Home Integration
- **Home Assistant**
  * **Enhancement (Nov 21, 2025)**: Added `referral_code` field to Home Assistant endpoint for displaying client referral information in smart home dashboards.

### Authentication
- **Facebook OAuth**

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