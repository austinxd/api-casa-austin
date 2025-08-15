from django.contrib import admin

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto
from .pricing_models import (
    ExchangeRate,
    PropertyPricing,
    SeasonPricing,
    SpecialDatePricing,
    DiscountCode,
    AdditionalService,
    CancellationPolicy,
    AutomaticDiscount
)


class PropertyPhotoInline(admin.TabularInline):
    model = PropertyPhoto
    extra = 1
    fields = ("image_file", "image_url", "alt_text", "order", "is_main")
    ordering = ["order"]

    def get_queryset(self, request):
        """Solo mostrar fotos no eliminadas en el inline"""
        return PropertyPhoto.objects.filter(deleted=False)

    def delete_model(self, request, obj):
        """Realizar eliminación física en el inline"""
        super().delete_model(request, obj)  # Eliminación física real


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
        """Realizar eliminación física"""
        super().delete_model(request, obj)  # Eliminación física real

    def delete_queryset(self, request, queryset):
        """Realizar eliminación física en eliminación masiva"""
        queryset.delete()  # Eliminación física real

    actions = ['restore_photos', 'hard_delete_photos']

    def restore_photos(self, request, queryset):
        """Acción para restaurar fotos eliminadas"""
        count = queryset.update(deleted=False)
        self.message_user(request, f'{count} fotos han sido restauradas.')
    restore_photos.short_description = "Restaurar fotos seleccionadas"

    def hard_delete_photos(self, request, queryset):
        """Acción para eliminar físicamente las fotos de la base de datos"""
        count = queryset.count()
        queryset.delete()  # Eliminación física real
        self.message_user(request, f'{count} fotos han sido eliminadas permanentemente de la base de datos.')
    hard_delete_photos.short_description = "ELIMINAR PERMANENTEMENTE fotos seleccionadas"


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


class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('usd_to_sol', 'is_active', 'created', 'updated')
    list_filter = ('is_active',)
    actions = ['make_active']

    def make_active(self, request, queryset):
        # Desactivar todos primero
        ExchangeRate.objects.update(is_active=False)
        # Activar seleccionados
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} tipos de cambio activados.')
    make_active.short_description = "Activar tipos de cambio seleccionados"


@admin.register(PropertyPricing)
class PropertyPricingAdmin(admin.ModelAdmin):
    list_display = ('property', 'weekday_low_season_usd', 'weekend_low_season_usd', 'weekday_high_season_usd', 'weekend_high_season_usd')
    list_filter = ('property',)
    search_fields = ('property__name',)
    fieldsets = (
        ('Información General', {
            'fields': ('property',)
        }),
        ('Precios Temporada Baja', {
            'fields': ('weekday_low_season_usd', 'weekend_low_season_usd'),
            'description': 'Precios base para temporada baja'
        }),
        ('Precios Temporada Alta', {
            'fields': ('weekday_high_season_usd', 'weekend_high_season_usd'),
            'description': 'Precios base para temporada alta'
        }),
    )


@admin.register(SeasonPricing)
class SeasonPricingAdmin(admin.ModelAdmin):
    list_display = ('name', 'season_type', 'get_date_range_display', 'is_active')
    list_filter = ('season_type', 'is_active', 'start_month', 'end_month')
    search_fields = ('name',)
    fieldsets = (
        ('Información de Temporada Global Recurrente', {
            'fields': ('name', 'season_type', 'is_active'),
            'description': 'Esta temporada se aplicará a TODAS las propiedades cada año'
        }),
        ('Período de la Temporada', {
            'fields': (
                ('start_month', 'start_day'),
                ('end_month', 'end_day')
            ),
            'description': 'Define el rango de fechas que se repetirá cada año. Ejemplo: Verano del 15 de Diciembre al 15 de Marzo'
        }),
    )
    
    def get_date_range_display(self, obj):
        """Muestra el rango de fechas en formato legible"""
        return obj.get_date_range_display()
    get_date_range_display.short_description = 'Período'

@admin.register(SpecialDatePricing)
class SpecialDatePricingAdmin(admin.ModelAdmin):
    list_display = ('property', 'description', 'get_date_display', 'price_usd', 'is_active')
    list_filter = ('is_active', 'property', 'month')
    search_fields = ('property__name', 'description')
    fieldsets = (
        ('Información de la Fecha Especial Recurrente', {
            'fields': ('property', 'description', 'is_active'),
            'description': 'Esta fecha especial se aplicará cada año para la propiedad seleccionada'
        }),
        ('Fecha de la Ocasión Especial', {
            'fields': (
                ('month', 'day'),
            ),
            'description': 'Define el día y mes que se repetirá cada año. Ejemplo: 25 de Diciembre para Navidad'
        }),
        ('Precio Especial', {
            'fields': ('price_usd',),
            'description': 'Precio base especial para esta fecha'
        }),
    )
    
    def get_date_display(self, obj):
        """Muestra la fecha en formato legible"""
        return obj.get_date_display()
    get_date_display.short_description = 'Fecha'


class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'discount_type', 'discount_value', 'used_count', 'usage_limit', 'is_active')
    list_filter = ('discount_type', 'is_active')
    search_fields = ('code', 'description')
    filter_horizontal = ('properties',)
    readonly_fields = ('used_count',)


class AdditionalServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_usd', 'service_type', 'is_per_night', 'is_per_person', 'is_active')
    list_filter = ('service_type', 'is_per_night', 'is_per_person', 'is_active')
    search_fields = ('name', 'description')
    filter_horizontal = ('properties',)


class CancellationPolicyAdmin(admin.ModelAdmin):
    list_display = ('name', 'days_before_checkin', 'refund_percentage', 'is_default', 'is_active')
    list_filter = ('is_default', 'is_active')
    search_fields = ('name', 'description')
    filter_horizontal = ('properties',)
    actions = ['make_default']

    def make_default(self, request, queryset):
        # Desactivar todos los defaults primero
        CancellationPolicy.objects.update(is_default=False)
        # Activar seleccionados
        updated = queryset.update(is_default=True)
        self.message_user(request, f'{updated} políticas marcadas como por defecto.')
    make_default.short_description = "Marcar como política por defecto"


class AutomaticDiscountAdmin(admin.ModelAdmin):
    list_display = ('name', 'trigger', 'discount_percentage', 'max_discount_usd', 'min_reservations', 'is_active')
    list_filter = ('trigger', 'is_active')
    search_fields = ('name',)


# Configurar títulos del admin para organizar mejor
admin.site.site_header = "Casa Austin - Panel de Administración"
admin.site.site_title = "Casa Austin Admin"
admin.site.index_title = "Gestión de Casa Austin"

# Registrar modelos principales de Property
admin.site.register(Property, PropertyAdmin)
admin.site.register(PropertyPhoto, PropertyPhotoAdmin)
admin.site.register(ProfitPropertyAirBnb)

# Registrar modelos de precios en el admin
admin.site.register(ExchangeRate, ExchangeRateAdmin)
# Previously, SeasonPricing was registered directly, now it uses the @admin.register decorator.
admin.site.register(DiscountCode, DiscountCodeAdmin)
admin.site.register(AdditionalService, AdditionalServiceAdmin)
admin.site.register(CancellationPolicy, CancellationPolicyAdmin)
admin.site.register(AutomaticDiscount, AutomaticDiscountAdmin)