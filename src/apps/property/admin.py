from django.contrib import admin

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto


class PropertyPhotoInline(admin.TabularInline):
    model = PropertyPhoto
    extra = 1
    fields = ("image_file", "image_url", "alt_text", "order", "is_main")
    ordering = ["order"]
    
    def get_queryset(self, request):
        """Solo mostrar fotos no eliminadas en el inline"""
        return PropertyPhoto.objects.filter(deleted=False)
    
    def delete_model(self, request, obj):
        """Realizar soft delete en el inline"""
        obj.deleted = True
        obj.save()


class PropertyPhotoAdmin(admin.ModelAdmin):
    list_display = ("property", "alt_text", "order", "is_main", "deleted")
    list_filter = ("is_main", "deleted", "property")
    search_fields = ("property__name", "alt_text")
    ordering = ["property", "order"]
    fields = ("property", "image_file", "image_url", "alt_text", "order", "is_main")
    
    def get_queryset(self, request):
        """Mostrar todas las fotos incluyendo las eliminadas (soft delete)"""
        return PropertyPhoto.objects.all()
    
    def delete_model(self, request, obj):
        """Realizar soft delete en lugar de hard delete"""
        obj.deleted = True
        obj.save()
    
    def delete_queryset(self, request, queryset):
        """Realizar soft delete en eliminación masiva"""
        queryset.update(deleted=True)
    
    actions = ['restore_photos']
    
    def restore_photos(self, request, queryset):
        """Acción para restaurar fotos eliminadas"""
        count = queryset.update(deleted=False)
        self.message_user(request, f'{count} fotos han sido restauradas.')
    restore_photos.short_description = "Restaurar fotos seleccionadas"


class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "titulo",
        "slug",
        "location",
        "dormitorios",
        "banos",
        "precio_extra_persona",
        "precio_desde",
        "deleted"
    )
    list_filter = ("dormitorios", "banos", "deleted")
    search_fields = ("name", "titulo", "location", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [PropertyPhotoInline]
    fieldsets = (
        ("Información Básica", {
            "fields": ("name", "titulo", "slug", "descripcion", "location", "background_color")
        }),
        ("Detalles de Alojamiento", {
            "fields": ("dormitorios", "banos", "detalle_dormitorios", "capacity_max", "caracteristicas")
        }),
        ("Horarios y Precios", {
            "fields": ("hora_ingreso", "hora_salida", "precio_extra_persona", "precio_desde")
        }),
        ("URLs", {
            "fields": ("airbnb_url", "on_temperature_pool_url", "off_temperature_pool_url")
        })
    )


admin.site.register(Property, PropertyAdmin)
admin.site.register(PropertyPhoto, PropertyPhotoAdmin)
admin.site.register(ProfitPropertyAirBnb)