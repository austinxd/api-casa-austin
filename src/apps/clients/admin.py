from django.contrib import admin

from .models import Clients, MensajeFidelidad, TokenApiClients, ReferralPointsConfig, ClientPoints, Achievement, ClientAchievement
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


@admin.register(ReferralPointsConfig)
class ReferralPointsConfigAdmin(admin.ModelAdmin):
    list_display = ('percentage', 'is_active', 'created', 'updated')
    list_filter = ('is_active', 'created')
    readonly_fields = ('created', 'updated')

@admin.register(ClientPoints)
class ClientPointsAdmin(admin.ModelAdmin):
    list_display = ('client', 'transaction_type', 'points', 'reservation', 'referred_client', 'created')
    list_filter = ('transaction_type', 'created')
    search_fields = ('client__first_name', 'client__last_name', 'referred_client__first_name', 'referred_client__last_name')
    readonly_fields = ('created', 'updated')


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('name', 'required_reservations', 'required_referrals', 'required_referral_reservations', 'is_active', 'order')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    ordering = ('order', 'required_reservations')
    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'description', 'icon', 'is_active', 'order')
        }),
        ('Requisitos', {
            'fields': ('required_reservations', 'required_referrals', 'required_referral_reservations'),
            'description': 'Configure los requisitos mínimos para obtener este logro'
        }),
    )
    
    actions = ['check_all_clients_for_achievement']
    
    def check_all_clients_for_achievement(self, request, queryset):
        """Acción admin para verificar todos los clientes para los logros seleccionados"""
        from .models import Clients, ClientAchievement
        
        total_awarded = 0
        for achievement in queryset:
            if not achievement.is_active:
                continue
                
            for client in Clients.objects.filter(deleted=False):
                if achievement.check_client_qualifies(client):
                    # Verificar si ya tiene el logro
                    if not ClientAchievement.objects.filter(client=client, achievement=achievement).exists():
                        ClientAchievement.objects.create(client=client, achievement=achievement)
                        total_awarded += 1
        
        self.message_user(request, f'Se otorgaron {total_awarded} nuevos logros')
    check_all_clients_for_achievement.short_description = "Verificar y otorgar logros a todos los clientes"


@admin.register(ClientAchievement)
class ClientAchievementAdmin(admin.ModelAdmin):
    list_display = ('client', 'achievement', 'earned_at')
    list_filter = ('achievement', 'earned_at')
    search_fields = ('client__first_name', 'client__last_name', 'achievement__name')
    readonly_fields = ('earned_at',)
    autocomplete_fields = ('client', 'achievement')

admin.site.register(MensajeFidelidad, MensajeFidelidadAdmin)
admin.site.register(TokenApiClients)
admin.site.register(Clients, ClientsAdmin)