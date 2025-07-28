# Incorporating ClientPoints model into admin and defining its admin class.
from django.contrib import admin
from .models import Clients, MensajeFidelidad, TokenApiClients, ClientPoints

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

class ClientPointsAdmin(admin.ModelAdmin):
    list_display = ('client', 'transaction_type', 'points', 'reservation', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('client__first_name', 'client__last_name', 'description')
    readonly_fields = ('created_at',)


admin.site.register(Clients, ClientsAdmin)
admin.site.register(TokenApiClients)
admin.site.register(MensajeFidelidad, MensajeFidelidadAdmin)
admin.site.register(ClientPoints, ClientPointsAdmin)