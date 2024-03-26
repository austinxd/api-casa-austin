from django.contrib import admin

from .models import Property


class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "location",
    )


admin.site.register(Property, PropertyAdmin)