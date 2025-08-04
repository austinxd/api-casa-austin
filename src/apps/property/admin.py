from django.contrib import admin

from .models import Property, ProfitPropertyAirBnb


class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "titulo",
        "location",
        "dormitorios",
        "banos",
        "precio_extra_persona",
        "deleted"
    )
    list_filter = ("dormitorios", "banos", "deleted")
    search_fields = ("name", "titulo", "location")
    fieldsets = (
        ("Información Básica", {
            "fields": ("name", "titulo", "descripcion", "location", "background_color")
        }),
        ("Detalles de Alojamiento", {
            "fields": ("dormitorios", "banos", "detalle_dormitorios", "capacity_max", "caracteristicas")
        }),
        ("Horarios y Precios", {
            "fields": ("hora_ingreso", "hora_salida", "precio_extra_persona")
        }),
        ("URLs", {
            "fields": ("airbnb_url", "on_temperature_pool_url", "off_temperature_pool_url")
        })
    )


admin.site.register(Property, PropertyAdmin)
admin.site.register(ProfitPropertyAirBnb)