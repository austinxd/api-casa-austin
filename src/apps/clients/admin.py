from django.contrib import admin
from .models import Clients, TokenApiClients

class ClientsAdmin(admin.ModelAdmin):
    model = Clients
    search_fields = ['last_name', "first_name", "number_doc"]
    list_display = (
        "last_name",
        "first_name",
        "number_doc",
        "deleted"
    )


admin.site.register(Clients, ClientsAdmin)
admin.site.register(TokenApiClients)
