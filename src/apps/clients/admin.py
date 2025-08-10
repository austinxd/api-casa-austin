from django.contrib import admin

from .models import Clients, MensajeFidelidad, TokenApiClients, ReferralPointsConfig, ClientPoints
from apps.core.utils import ExportCsvMixin, ExportJsonMixin


class ClientsAdmin(admin.ModelAdmin, ExportCsvMixin, ExportJsonMixin):
    model = Clients
    list_filter = ("deleted", "sex",)
    search_fields = ['last_name', "first_name", "number_doc", "tel_number"]
    list_display = (
        "id",
        "last_name",
        "first_name",
        "number_doc",
        "sex",
        "tel_number",
        "deleted"
    )
    actions = ["export_as_csv", "export_as_json"]

class MensajeFidelidadAdmin(admin.ModelAdmin):
    model = MensajeFidelidad
    list_filter = ("activo", )
    search_fields = ['mensaje', "activo"]
    list_display = (
        "id",
        "mensaje",
        "activo",
    )
    actions = ["export_as_csv", "export_as_json"]


@admin.register(ReferralPointsConfig)
class ReferralPointsConfigAdmin(admin.ModelAdmin):
    list_display = ('percentage', 'is_active', 'created', 'updated')
    list_filter = ('is_active', 'created')
    readonly_fields = ('created', 'updated')

@admin.register(ClientPoints)
class ClientPointsAdmin(admin.ModelAdmin):
    list_display = ('client', 'transaction_type', 'points', 'reservation', 'referred_client', 'created')
    list_filter = ('transaction_type', 'created')
    search_fields = ('client__first_name', 'client__last_name', 'referred_client__first_name', 'referred_client__last_name')
    readonly_fields = ('created', 'updated')

admin.site.register(Clients)
admin.site.register(MensajeFidelidad)
admin.site.register(TokenApiClients)