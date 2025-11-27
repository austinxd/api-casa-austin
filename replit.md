# Casa Austin - Property Reservation API

## Overview
Casa Austin is a Django REST API for managing vacation rental properties. It provides a comprehensive booking experience by handling reservations, client management, payment processing, and integrations with external services. The system optimizes booking workflows, enhances customer loyalty through a points system, and offers robust management tools including dynamic pricing, discount management, referral tracking, and advanced analytics.

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
- **Property App**: Property listings, photos, dynamic pricing, configurations, and current USD to SOL exchange rate.
- **Reservation App**: Booking workflows, payment processing, reservation lifecycle, availability search.
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
- Late checkout pricing configuration.
- Referral discount system for first-time reservations based on referrer's achievement level.
- Dynamic discount code generator with customizable prefixes, percentages, validity, and usage limits.
- Configurable welcome discount system for new user registrations with automatic code generation, public status endpoint, and specific weekday selection.

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
- Contract generation system supporting natural persons (DNI, Passport, Carnet de Extranjería) and companies (RUC), automatically selecting the appropriate DOCX template and generating PDF contracts.

### Technical Implementations
- ERP pricing endpoint integration for smart availability search.
- Enhanced points system with clear transaction types and staff adjustment capabilities.
- Bulk import commands for historical data.
- Unified referral statistics API with flexible filtering.
- Event evidence upload system with admin approval and SEO-friendly slugs.
- QR Code reservation endpoint displaying client info, referral code, and discount.
- Client info by referral code endpoint showing client data and active reservations.
- Client profile endpoint enhanced to show referral discount information.
- Public endpoint `/api/v1/active/` for listing currently active reservations with guest count, check-in information, pool heating status, late checkout, comments, and client phone number.
- Reservations API filter `created_today=true` to list reservations created on the current date, using UTC boundary ranges.
- Music System Integration migrated to a custom Deezer-based HTTP API for streaming and player control, with reservation-based sessions, host approval workflow, time-based validation, and auto-power management for DLNA players. Includes `late_checkout` status in music and QR code endpoints.
- Contact Synchronization script (`sync_contacts_nextcloud.py`) to Nextcloud via WebDAV, showing real-time reservation status, client points, and referral codes.

## External Dependencies

### Payment Gateways
- **MercadoPago**
- **OpenPay**

### Communication Services
- **Twilio**
- **Telegram Bot API**
- **WhatsApp Business API**
- **Expo Push Notifications**: Dual notification system for clients and administrators with device token management, pre-built templates for various events (reservations, client registration), and automatic push notifications via Django signals. Includes smart notification consolidation (multiple changes trigger ONE notification), advance payment tracking with currency support, price changes in both USD and PEN, origin and seller tracking for admin notifications, and comprehensive notification history with admin and client-facing endpoints. Complete 22-notification system: 15 for clients, 7 for admins (including new client registration alerts).

### Data and Analytics
- **Google Sheets API**
- **ChatGPT Builder API**

### Smart Home Integration
- **Home Assistant**: Integration for device control (lights, switches, climate) per property with guest access control and location-based grouping. Client device control API allows guests with active reservations to manage devices securely.

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