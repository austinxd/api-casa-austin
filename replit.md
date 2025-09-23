# Casa Austin - Property Reservation API

## Overview

Casa Austin is a Django REST API application for managing vacation rental properties. The system handles property reservations, client management, payment processing, and integrates with external services for a complete booking experience. The application serves as the backend for Casa Austin's property rental business, managing multiple vacation homes with comprehensive booking workflows.

## User Preferences

Preferred communication style: Simple, everyday language.

## Recent Changes

### September 23, 2025 - Referral Ranking System Implementation
- **New Feature**: Complete monthly referral ranking system to track clients with highest referral activity
- **Database Schema**: New `ReferralRanking` model tracks monthly statistics for each client
- **API Endpoints**: Three new endpoints for referral analytics:
  - `/api/v1/clients/referral-ranking/` - Historical ranking data with year/month parameters
  - `/api/v1/clients/referral-ranking/current/` - Current month ranking leaderboard  
  - `/api/v1/clients/referral-stats/` - **Public access** general referral statistics (no authentication required)
- **Authentication Changes**: Made referral-stats endpoint public while maintaining authentication for other client endpoints
- **URL Routing Fix**: Resolved URL pattern conflicts by placing specific patterns before router includes
- **Management Command**: `calculate_referral_ranking` command for monthly ranking calculation
- **Admin Interface**: Full Django admin integration with ranking recalculation actions
- **Metrics Tracked**: Reservations by referrals, referral revenue, new referrals made, points earned, ranking position

### September 21, 2025 - Modular Analytics Architecture Implementation
- **Breaking Change**: Replaced monolithic `/stats/` endpoint with specific modular endpoints:
  - `/api/v1/stats/search-tracking/` - Dedicated search analytics with privacy-focused data
  - `/api/v1/stats/ingresos/` - Specific revenue and financial metrics
  - `/api/v1/upcoming-checkins/` - Check-ins analysis and trending dates
- **Security Enhancement**: All analytics endpoints now require authentication (IsAuthenticated)
- **Data Model Corrections**: Fixed field mappings for SearchTracking.search_timestamp and Reservation.price_sol
- **Performance**: Manual nights calculation implemented since Reservation model lacks nights field
- **Privacy**: Maintained IP anonymization and "FirstName L." format for client data
- **Deprecation**: ComprehensiveStatsView marked as deprecated, use specific endpoints instead

## System Architecture

### Backend Framework
- **Django 4.2.11** with Django REST Framework for API development
- **Gunicorn** as the WSGI server for production deployment
- **MySQL** database for production with SQLite fallback for development
- Modular app structure with separate Django apps for different business domains

### Core Applications
- **Clients App**: Manages client authentication, profiles, and customer data
- **Property App**: Handles property listings, photos, pricing, and configurations
- **Reservation App**: Manages booking workflows, payments, and reservation lifecycle
- **Staff App**: Comprehensive staff management system with automatic cleaning task assignment, intelligent staff scheduling, time tracking, and workload distribution
- **Accounts App**: User management and administrative functions

### Payment Processing
- **Multi-gateway support** with MercadoPago and OpenPay integrations
- **Token-based payment validation** to prevent duplicate transactions
- **Voucher upload system** with deadline management for manual payment verification
- **Points and achievements system** for customer loyalty

### External Integrations
- **Facebook OAuth** integration for client verification with enterprise-grade security validation
- **Google Apps Script** integration for data export to Google Sheets
- **WhatsApp/Telegram** messaging for customer communication
- **ChatGPT Builder** API for discount management and automation
- **Home Assistant** integration for smart home features (pool temperature, etc.)
- **Calendar export** functionality with ICS file generation

### Search and Tracking
- **SearchTracking system** for monitoring customer search patterns
- **Export capabilities** to Google Sheets for analytics
- **Anonymous user tracking** with fallback data structures

### Pricing and Discounts
- **Dynamic pricing** based on seasons and special dates
- **Automatic discount system** with achievement-based triggers
- **Discount codes** with weekend/weekday restrictions
- **Late checkout** pricing and configuration

### Authentication and Security
- **JWT-based authentication** with SimpleJWT
- **CORS handling** for cross-origin requests
- **Environment-based configuration** using django-environ
- **API documentation** with DRF Spectacular

### File Management
- **Image processing** with Pillow for property photos
- **Document handling** for vouchers and receipts
- **Media file management** with proper URL handling

## External Dependencies

### Payment Gateways
- **MercadoPago**: Primary payment processor for card transactions
- **OpenPay**: Secondary payment processor with sandbox/production modes

### Communication Services
- **Twilio**: SMS and messaging services
- **Telegram Bot API**: Automated internal notifications and customer communications
- **WhatsApp Business API**: Customer communication workflows including OTP verification, payment confirmations, reservation cancellations, and welcome messages for new registrations

### Data and Analytics
- **Google Sheets API**: Via Google Apps Script for data export and reporting
- **ChatGPT Builder API**: For automated discount and promotion management

### Smart Home Integration
- **Home Assistant**: Property automation and monitoring (pool temperature, security)

### Third-Party Libraries
- **python-telegram-bot**: Telegram integration
- **requests**: HTTP client for external API calls
- **Pillow**: Image processing and manipulation
- **docxtpl**: Document template processing
- **icalendar**: Calendar file generation
- **babel**: Internationalization support

### Development and Deployment
- **django-cors-headers**: CORS policy management
- **drf-spectacular**: API documentation generation
- **python-slugify**: URL slug generation
- **python-dateutil**: Advanced date/time handling