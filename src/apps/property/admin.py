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


# Inline para fechas especiales dentro de cada propiedad
class SpecialDatePricingInline(admin.TabularInline):
    model = SpecialDatePricing
    extra = 3
    fields = ('month', 'day', 'description', 'price_usd', 'is_active')
    ordering = ['month', 'day']
    verbose_name = "Fecha Especial"
    verbose_name_plural = "🎉 Fechas Especiales para esta Propiedad"
    classes = ['collapse']

    def get_queryset(self, request):
        """Solo mostrar fechas especiales activas"""
        return SpecialDatePricing.objects.filter(deleted=False)


# Inline especial para fechas especiales en PropertyPricing
class SpecialDatePricingForPropertyPricingInline(admin.TabularInline):
    model = SpecialDatePricing
    extra = 5
    fields = ('month', 'day', 'description', 'price_usd', 'is_active')
    ordering = ['month', 'day']
    verbose_name = "Fecha Especial"
    verbose_name_plural = "🎉 Agregar Fechas Especiales (Navidad, Año Nuevo, etc.)"
    
    def get_queryset(self, request):
        """Mostrar fechas especiales de la propiedad relacionada"""
        return SpecialDatePricing.objects.filter(deleted=False)
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Auto-establecer la propiedad basada en el PropertyPricing"""
        if db_field.name == "property":
            # Obtener el PropertyPricing del URL
            pricing_id = request.resolver_match.kwargs.get('object_id')
            if pricing_id:
                try:
                    from .pricing_models import PropertyPricing
                    pricing = PropertyPricing.objects.get(pk=pricing_id)
                    kwargs["initial"] = pricing.property.pk
                    kwargs["disabled"] = True
                except PropertyPricing.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def get_formset(self, request, obj=None, **kwargs):
        """Personalizar el formset para auto-establecer la propiedad"""
        formset = super().get_formset(request, obj, **kwargs)
        
        class CustomFormSet(formset):
            def save_new(self, form, commit=True):
                """Auto-establecer la propiedad al guardar nuevas fechas especiales"""
                instance = form.save(commit=False)
                if obj:  # obj es el PropertyPricing
                    instance.property = obj.property
                if commit:
                    instance.save()
                return instance
        
        return CustomFormSet


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
    inlines = [PropertyPhotoInline, SpecialDatePricingInline]
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
    
    def get_inline_instances(self, request, obj=None):
        """Customizar los inlines según el contexto"""
        inlines = super().get_inline_instances(request, obj)
        if obj:  # Solo mostrar fechas especiales si la propiedad ya existe
            return inlines
        else:  # Si es nueva propiedad, solo mostrar fotos
            return [inline for inline in inlines if isinstance(inline, PropertyPhotoInline)]


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
    list_display = ('property', 'weekday_low_season_usd', 'weekend_low_season_usd', 'weekday_high_season_usd', 'weekend_high_season_usd', 'get_special_dates_count')
    list_filter = ('property',)
    search_fields = ('property__name',)
    inlines = [SpecialDatePricingForPropertyPricingInline]
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
    
    def get_special_dates_count(self, obj):
        """Muestra cuántas fechas especiales tiene la propiedad"""
        count = obj.property.special_date_pricing.filter(deleted=False, is_active=True).count()
        if count == 0:
            return "Sin fechas especiales"
        return f"{count} fecha{'s' if count != 1 else ''} especial{'es' if count != 1 else ''}"
    get_special_dates_count.short_description = "Fechas Especiales"


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

class SpecialDatePricingAdmin(admin.ModelAdmin):
    list_display = ('property', 'description', 'get_date_display', 'price_usd', 'is_active')
    list_filter = ('is_active', 'property', 'month')
    search_fields = ('property__name', 'description')
    
    # Agrupar por propiedad
    list_display_links = ('description',)
    
    def get_queryset(self, request):
        """Ordenar por propiedad y luego por fecha"""
        return super().get_queryset(request).select_related('property').order_by('property__name', 'month', 'day')
    
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
    
    def changelist_view(self, request, extra_context=None):
        """Agregar contexto adicional a la vista de lista"""
        extra_context = extra_context or {}
        extra_context['bulk_special_dates_url'] = '/property/admin/bulk-special-dates/'
        extra_context['property_manager_url'] = '/property/admin/special-dates-manager/'
        
        # URL para gestión de fechas por propiedad - usar URL directa
        extra_context['property_dates_url'] = '/property/admin/special-dates-manager/'
        
        # Agrupar fechas especiales por propiedad para mejor visualización
        from collections import defaultdict
        special_dates_by_property = defaultdict(list)
        
        for special_date in SpecialDatePricing.objects.select_related('property').filter(deleted=False).order_by('property__name', 'month', 'day'):
            special_dates_by_property[special_date.property].append(special_date)
        
        extra_context['special_dates_by_property'] = dict(special_dates_by_property)
        
        return super().changelist_view(request, extra_context)
    
    class Media:
        css = {
            'all': ('admin/css/changelists.css',)
        }
        js = ()
    
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('bulk-add/', self.admin_site.admin_view(self.bulk_add_view), name='bulk-add-special-dates'),
        ]
        return custom_urls + urls
    
    def bulk_add_view(self, request):
        """Redireccionar a la vista de carga masiva"""
        from django.shortcuts import redirect
        return redirect('/property/admin/bulk-special-dates/')


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
# SpecialDatePricing ya no se registra aquí - se maneja solo a través de inlines