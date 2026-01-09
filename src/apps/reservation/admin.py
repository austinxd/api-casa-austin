from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Reservation, RentalReceipt


class ReservationAdmin(SimpleHistoryAdmin):
    search_fields = ['property__name', 'origin', 'client__first_name', 'client__last_name']
    list_filter = ("deleted", "origin", "status", "property")
    list_display = (
        "id",
        "client",
        "property",
        "check_in_date",
        "check_out_date",
        "status",
        "origin",
        "deleted"
    )
    readonly_fields = ('created', 'updated')
    history_list_display = ['status', 'deleted', 'full_payment']  # Campos a mostrar en el historial

    fieldsets = (
        ('Información de la Reserva', {
            'fields': ('client', 'property', 'check_in_date', 'check_out_date', 'guests', 'status', 'origin')
        }),
        ('Precios', {
            'fields': ('price_usd', 'price_sol', 'advance_payment', 'advance_payment_currency', 'full_payment'),
            'classes': ('collapse',)
        }),
        ('Servicios Adicionales', {
            'fields': ('late_checkout', 'late_check_out_date', 'temperature_pool', 'price_latecheckout', 'price_temperature_pool'),
            'classes': ('collapse',)
        }),
        ('Comentarios', {
            'fields': ('comentarios_reservas',),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('ip_cliente', 'user_agent', 'referer', 'fbclid', 'utm_source', 'utm_medium', 'utm_campaign'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created', 'updated', 'deleted'),
            'classes': ('collapse',)
        }),
    )


admin.site.register(Reservation, ReservationAdmin)
admin.site.register(RentalReceipt)
