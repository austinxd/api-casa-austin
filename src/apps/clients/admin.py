from django.contrib import admin
from .models import Clients, MensajeFidelidad, TokenApiClients

from apps.core.utils import ExportCsvMixin, ExportJsonMixin


class ClientsAdmin(admin.ModelAdmin, ExportCsvMixin, ExportJsonMixin):
    model = Clients
    search_fields = ['last_name', "first_name", "number_doc", "tel_number"]
    list_display = (
        "id",
        "last_name",
        "first_name",
        "number_doc",
        "tel_number",
        "deleted"
    )
    actions = ["export_as_csv", "export_as_json"]


admin.site.register(Clients, ClientsAdmin)
admin.site.register(MensajeFidelidad)
admin.site.register(TokenApiClients)
