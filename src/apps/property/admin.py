from django.contrib import admin

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto, ReferralDiscountByLevel
from .pricing_models import (
    ExchangeRate,
    PropertyPricing,
    SeasonPricing,
    SpecialDatePricing,
    DiscountCode,
    DynamicDiscountConfig,
    AdditionalService,
    CancellationPolicy,
    AutomaticDiscount,
    LateCheckoutConfig
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
        }),
        ("🎵 Music Assistant", {
            "fields": ("player_id",),
            "classes": ("collapse",),
            "description": "ID del reproductor de Music Assistant vinculado a esta propiedad. Obtén el player_id desde el endpoint /api/v1/music/players/"
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
        """Muestra cuántas fechas especiales tiene la propiedad con enlace para gestionarlas"""
        from django.utils.html import format_html
        from django.urls import reverse

        count = obj.property.special_date_pricing.filter(deleted=False, is_active=True).count()

        # Crear enlace directo al admin de la propiedad donde están las fechas especiales
        property_admin_url = reverse('admin:property_property_change', args=[obj.property.id])

        if count == 0:
            return format_html(
                '<a href="{}">⚠️ Sin fechas especiales - Gestionar</a>',
                property_admin_url
            )
        return format_html(
            '<a href="{}">{} fecha{} especial{} - Gestionar</a>',
            property_admin_url,
            count,
            's' if count != 1 else '',
            'es' if count != 1 else ''
        )
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

@admin.register(SpecialDatePricing)
class SpecialDatePricingAdmin(admin.ModelAdmin):
    list_display = ('property', 'get_date_display', 'description', 'price_usd', 'minimum_consecutive_nights', 'is_active')
    list_filter = ('is_active', 'month', 'minimum_consecutive_nights', 'property')
    search_fields = ('property__name', 'description')
    ordering = ('property', 'month', 'day')

    # Agrupar por propiedad
    list_display_links = ('description',)

    def get_queryset(self, request):
        """Ordenar por propiedad y luego por fecha"""
        return super().get_queryset(request).select_related('property').order_by('property__name', 'month', 'day')

    fieldsets = (
        ('Información de la Fecha Especial', {
            'fields': ('property', 'description', 'is_active'),
            'description': 'Fecha especial para la propiedad seleccionada'
        }),
        ('Fecha de la Ocasión Especial', {
            'fields': (
                ('month', 'day'),
            ),
            'description': 'Define el día y mes. Ejemplo: 25 de Diciembre para Navidad'
        }),
        ('Precio Especial', {
            'fields': ('price_usd',),
            'description': 'Precio base especial para esta fecha'
        }),
        ('Restricciones', {
            'fields': ('minimum_consecutive_nights',),
            'description': 'Mínimo de noches consecutivas para aplicar este precio especial.'
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


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'discount_type', 'discount_value', 'used_count', 'usage_limit', 'get_day_restrictions', 'is_active')
    list_filter = ('discount_type', 'is_active', 'restrict_weekdays', 'restrict_weekends')
    search_fields = ('code', 'description')
    filter_horizontal = ('properties',)
    readonly_fields = ('used_count',)

    fieldsets = (
        ('Información del Código', {
            'fields': ('code', 'description', 'is_active')
        }),
        ('Configuración de Descuento', {
            'fields': ('discount_type', 'discount_value', 'min_amount_usd', 'max_discount_usd')
        }),
        ('Validez', {
            'fields': ('start_date', 'end_date', 'usage_limit', 'used_count')
        }),
        ('Restricciones', {
            'fields': ('properties', 'restrict_weekdays', 'restrict_weekends'),
            'description': 'Restricciones de aplicabilidad del código'
        }),
    )

    def get_day_restrictions(self, obj):
        """Muestra las restricciones de días de forma legible"""
        if obj.restrict_weekdays:
            return "🗓️ Solo días de semana"
        elif obj.restrict_weekends:
            return "🎉 Solo fines de semana"
        else:
            return "📅 Todos los días"
    get_day_restrictions.short_description = "Restricciones de Días"


class AdditionalServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_usd', 'service_type', 'is_per_night', 'is_per_person', 'is_active', 'post_action')
    list_filter = ('service_type', 'is_per_night', 'is_per_person', 'is_active')
    search_fields = ('name', 'description', 'post_action')
    filter_horizontal = ('properties',)
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'price_usd')
        }),
        ('Configuración', {
            'fields': ('service_type', 'is_per_night', 'is_per_person', 'is_active')
        }),
        ('Propiedades', {
            'fields': ('properties',)
        }),
        ('Acción Post-Reserva', {
            'fields': ('post_action',),
            'description': 'Acción que debe realizar el frontend después de la reserva (ej: temperature_pool)'
        }),
    )


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


@admin.register(AutomaticDiscount)
class AutomaticDiscountAdmin(admin.ModelAdmin):
    list_display = ('name', 'trigger', 'discount_percentage', 'max_discount_usd', 'get_date_validity', 'get_required_achievements', 'get_days_restriction', 'apply_only_to_base_price', 'is_active')
    list_filter = ('trigger', 'restrict_weekdays', 'restrict_weekends', 'is_active')
    search_fields = ('name', 'description')
    filter_horizontal = ('required_achievements',)

    fieldsets = (
        ('Información General', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('Configuración del Descuento', {
            'fields': ('trigger', 'discount_percentage', 'max_discount_usd', 'apply_only_to_base_price')
        }),
        ('Vigencia del Descuento', {
            'fields': ('start_date', 'end_date'),
            'description': 'Fechas de inicio y fin de validez del descuento (opcional). Si no se especifican, el descuento estará siempre activo.'
        }),
        ('Logros Requeridos', {
            'fields': ('required_achievements',),
            'description': 'Selecciona los logros que debe tener el cliente para aplicar este descuento'
        }),
        ('Restricciones de Días', {
            'fields': ('specific_weekdays', 'restrict_weekdays', 'restrict_weekends'),
            'description': '🆕 DÍAS ESPECÍFICOS: Ingresa números separados por comas (0=Lun, 1=Mar, 2=Mié, 3=Jue, 4=Vie, 5=Sáb, 6=Dom). Ejemplos: "4" = solo Viernes, "4,5" = Viernes y Sábado. Si usas días específicos, las otras opciones se ignoran.'
        }),
    )

    def get_date_validity(self, obj):
        """Muestra el periodo de validez del descuento"""
        if obj.start_date and obj.end_date:
            return f"📅 {obj.start_date.strftime('%d/%m/%Y')} - {obj.end_date.strftime('%d/%m/%Y')}"
        elif obj.start_date:
            return f"📅 Desde {obj.start_date.strftime('%d/%m/%Y')}"
        elif obj.end_date:
            return f"📅 Hasta {obj.end_date.strftime('%d/%m/%Y')}"
        else:
            return "♾️ Siempre activo"
    get_date_validity.short_description = "Vigencia"

    def get_required_achievements(self, obj):
        """Muestra los logros requeridos de forma legible"""
        achievements = obj.required_achievements.all()
        if not achievements:
            return "Sin restricciones de logros"
        return ", ".join([achievement.name for achievement in achievements])
    get_required_achievements.short_description = "Logros Requeridos"
    
    def get_days_restriction(self, obj):
        """Muestra la restricción de días de forma legible"""
        day_names = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        if obj.specific_weekdays:
            specific_days = [int(d.strip()) for d in obj.specific_weekdays.split(',') if d.strip().isdigit()]
            days_text = ', '.join([day_names[d] for d in specific_days if 0 <= d <= 6])
            return f"📌 {days_text}"
        elif obj.restrict_weekdays:
            return "📅 Días de semana"
        elif obj.restrict_weekends:
            return "🎉 Fines de semana"
        return "✨ Todos los días"
    get_days_restriction.short_description = "Días"



@admin.register(LateCheckoutConfig)
class LateCheckoutConfigAdmin(admin.ModelAdmin):
    list_display = ('get_weekday_display', 'allows_late_checkout', 'discount_type', 'discount_value', 'is_active')
    list_filter = ('allows_late_checkout', 'discount_type', 'is_active')
    list_editable = ('allows_late_checkout', 'discount_value', 'is_active')
    ordering = ['weekday']

    fieldsets = (
        ('Configuración del Día', {
            'fields': ('name', 'weekday', 'allows_late_checkout', 'is_active')
        }),
        ('Descuento para Late Checkout', {
            'fields': ('discount_type', 'discount_value'),
            'description': 'Descuento que se aplica cuando se cotiza un late checkout'
        }),
    )

    def get_weekday_display(self, obj):
        """Muestra el día de la semana en formato legible"""
        return obj.get_weekday_display()
    get_weekday_display.short_description = "Día de la semana"
    get_weekday_display.admin_order_field = 'weekday'


@admin.register(DynamicDiscountConfig)
class DynamicDiscountConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'prefix', 'discount_percentage', 'validity_days', 'min_amount_usd', 'usage_limit', 'apply_only_to_base_price', 'is_active')
    list_filter = ('is_active', 'apply_only_to_base_price', 'validity_days', 'properties')
    search_fields = ('name', 'prefix')
    filter_horizontal = ('properties',)

    fieldsets = (
        ('Información General', {
            'fields': ('name', 'prefix', 'is_active')
        }),
        ('Configuración del Descuento', {
            'fields': ('discount_percentage', 'min_amount_usd', 'max_discount_usd', 'usage_limit', 'apply_only_to_base_price'),
            'description': '💡 Si "Aplicar solo al precio base" está activo, el descuento NO incluirá huéspedes adicionales'
        }),
        ('Propiedades Aplicables', {
            'fields': ('properties',),
            'description': 'Selecciona las propiedades donde serán válidos los códigos generados. Si no seleccionas ninguna, los códigos no serán válidos para ninguna propiedad.'
        }),
        ('Validez', {
            'fields': ('validity_days',),
            'description': 'Los códigos generados serán válidos por este número de días desde su creación'
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        """Hacer algunos campos de solo lectura después de la creación"""
        if obj:  # Si está editando un objeto existente
            return ['prefix']
        return []


@admin.register(ReferralDiscountByLevel)
class ReferralDiscountByLevelAdmin(admin.ModelAdmin):
    list_display = ('achievement', 'discount_percentage', 'is_active')
    list_filter = ('is_active', 'achievement')
    search_fields = ('achievement__name',)
    
    fieldsets = (
        ('Configuración de Descuento por Nivel', {
            'fields': ('achievement', 'discount_percentage', 'is_active'),
            'description': 'Configura el descuento que recibirán los clientes referidos en su primera reserva, según el nivel del cliente que los refirió.'
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('achievement')


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
# SeasonPricing usa @admin.register decorator
# DiscountCode usa @admin.register decorator
# DynamicDiscountConfig usa @admin.register decorator
# SpecialDatePricing usa @admin.register decorator
admin.site.register(AdditionalService, AdditionalServiceAdmin)
admin.site.register(CancellationPolicy, CancellationPolicyAdmin)

# SpecialDatePricing ya no se registra aquí - se maneja solo a través de inlines