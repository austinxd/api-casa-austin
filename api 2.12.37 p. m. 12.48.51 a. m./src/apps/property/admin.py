from django.contrib import admin

from .models import Property, ProfitPropertyAirBnb


class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "location",
        "deleted"
    )


admin.site.register(Property, PropertyAdmin)
admin.site.register(ProfitPropertyAirBnb)