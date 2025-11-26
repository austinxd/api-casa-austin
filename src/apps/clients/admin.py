from django.contrib import admin

from .models import Clients, MensajeFidelidad, TokenApiClients, ReferralPointsConfig, ClientPoints, Achievement, ClientAchievement, ReferralRanking, PushToken, AdminPushToken, NotificationLog
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

@admin.register(ReferralRanking)
class ReferralRankingAdmin(admin.ModelAdmin):
    list_display = ('ranking_date_display', 'position', 'client', 'referral_reservations_count', 'total_referral_revenue', 'points_earned')
    list_filter = ('year', 'month', 'position')
    search_fields = ('client__first_name', 'client__last_name')
    readonly_fields = ('created', 'updated')
    ordering = ('-year', '-month', 'position')
    
    fieldsets = (
        ('Cliente y Período', {
            'fields': ('client', 'year', 'month', 'ranking_date_display')
        }),
        ('Estadísticas del Mes', {
            'fields': ('referral_reservations_count', 'total_referral_revenue', 'referrals_made_count', 'points_earned')
        }),
        ('Posición en Ranking', {
            'fields': ('position',)
        }),
        ('Fechas del Sistema', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )
    
    def ranking_date_display(self, obj):
        return obj.ranking_date_display
    ranking_date_display.short_description = 'Período'
    
    actions = ['recalculate_rankings']
    
    def recalculate_rankings(self, request, queryset):
        """Acción admin para recalcular rankings seleccionados"""
        from django.core.management import call_command
        
        # Obtener períodos únicos de los registros seleccionados
        periods = set()
        for ranking in queryset:
            periods.add((ranking.year, ranking.month))
        
        recalculated = 0
        for year, month in periods:
            try:
                call_command('calculate_referral_ranking', year=year, month=month, force=True, verbosity=0)
                recalculated += 1
            except Exception as e:
                self.message_user(request, f'Error recalculando {month}/{year}: {str(e)}', level='ERROR')
        
        if recalculated > 0:
            self.message_user(request, f'Se recalcularon {recalculated} períodos de ranking')
    recalculate_rankings.short_description = "Recalcular rankings de períodos seleccionados"


admin.site.register(MensajeFidelidad, MensajeFidelidadAdmin)
admin.site.register(TokenApiClients)
admin.site.register(Clients, ClientsAdmin)


@admin.register(PushToken)
class PushTokenAdmin(admin.ModelAdmin):
    list_display = ('client', 'device_type', 'is_active', 'last_used', 'failed_attempts', 'created')
    list_filter = ('device_type', 'is_active', 'created')
    search_fields = ('client__first_name', 'client__last_name', 'client__number_doc', 'device_name')
    readonly_fields = ('expo_token', 'created', 'updated', 'last_used')
    raw_id_fields = ('client',)
    
    fieldsets = (
        ('Cliente', {
            'fields': ('client',)
        }),
        ('Dispositivo', {
            'fields': ('expo_token', 'device_type', 'device_name')
        }),
        ('Estado', {
            'fields': ('is_active', 'failed_attempts', 'last_used')
        }),
        ('Fechas', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_tokens', 'deactivate_tokens', 'send_test_notification']
    
    def activate_tokens(self, request, queryset):
        updated = queryset.update(is_active=True, failed_attempts=0)
        self.message_user(request, f'{updated} token(s) activado(s)')
    activate_tokens.short_description = "Activar tokens seleccionados"
    
    def deactivate_tokens(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} token(s) desactivado(s)')
    deactivate_tokens.short_description = "Desactivar tokens seleccionados"
    
    def send_test_notification(self, request, queryset):
        from .expo_push_service import ExpoPushService
        
        sent = 0
        failed = 0
        for token in queryset.filter(is_active=True):
            result = ExpoPushService.send_push_notification(
                to=token.expo_token,
                title="Prueba Admin",
                body=f"Notificación de prueba para {token.client.first_name}",
                data={"type": "admin_test"}
            )
            if result.get("success"):
                sent += 1
                token.mark_as_used()
            else:
                failed += 1
        
        self.message_user(request, f'Enviadas: {sent}, Fallidas: {failed}')
    send_test_notification.short_description = "Enviar notificación de prueba"


@admin.register(AdminPushToken)
class AdminPushTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_type', 'is_active', 'last_used', 'failed_attempts', 'created')
    list_filter = ('device_type', 'is_active', 'created')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'device_name')
    readonly_fields = ('expo_token', 'created', 'updated', 'last_used')
    raw_id_fields = ('user',)
    
    fieldsets = (
        ('Usuario Administrador', {
            'fields': ('user',)
        }),
        ('Dispositivo', {
            'fields': ('expo_token', 'device_type', 'device_name')
        }),
        ('Estado', {
            'fields': ('is_active', 'failed_attempts', 'last_used')
        }),
        ('Fechas', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_tokens', 'deactivate_tokens', 'send_test_notification']
    
    def activate_tokens(self, request, queryset):
        updated = queryset.update(is_active=True, failed_attempts=0)
        self.message_user(request, f'{updated} token(s) de administrador activado(s)')
    activate_tokens.short_description = "Activar tokens seleccionados"
    
    def deactivate_tokens(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} token(s) de administrador desactivado(s)')
    deactivate_tokens.short_description = "Desactivar tokens seleccionados"
    
    def send_test_notification(self, request, queryset):
        from .expo_push_service import ExpoPushService
        
        sent = 0
        failed = 0
        for token in queryset.filter(is_active=True):
            result = ExpoPushService.send_push_notification(
                to=token.expo_token,
                title="Prueba Admin",
                body=f"Notificación de prueba para {token.user.get_full_name()}",
                data={"type": "admin_test"}
            )
            if result.get("success"):
                sent += 1
                token.mark_as_used()
            else:
                failed += 1
        
        self.message_user(request, f'Enviadas: {sent}, Fallidas: {failed}')
    send_test_notification.short_description = "Enviar notificación de prueba"

@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('custom_str', 'notification_type', 'recipient_info', 'success', 'read', 'sent_at')
    list_filter = ('notification_type', 'success', 'read', 'device_type', 'sent_at')
    search_fields = ('title', 'body', 'client__first_name', 'client__last_name', 'admin__first_name', 'admin__last_name')
    readonly_fields = ('sent_at', 'created', 'updated')
    date_hierarchy = 'sent_at'
    
    fieldsets = (
        ('Receptor', {
            'fields': ('client', 'admin')
        }),
        ('Contenido', {
            'fields': ('notification_type', 'title', 'body', 'data')
        }),
        ('Dispositivo', {
            'fields': ('expo_token', 'device_type')
        }),
        ('Estado', {
            'fields': ('success', 'error_message', 'read', 'read_at')
        }),
        ('Fechas', {
            'fields': ('sent_at', 'created', 'updated'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_read', 'mark_as_unread']
    
    def custom_str(self, obj):
        return str(obj)
    custom_str.short_description = 'Notificación'
    
    def recipient_info(self, obj):
        if obj.client:
            return f"Cliente: {obj.client.first_name} {obj.client.last_name}"
        elif obj.admin:
            return f"Admin: {obj.admin.get_full_name()}"
        return "Sin receptor"
    recipient_info.short_description = "Receptor"
    
    def mark_as_read(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(read=False).update(read=True, read_at=timezone.now())
        self.message_user(request, f'{updated} notificación(es) marcada(s) como leída(s)')
    mark_as_read.short_description = "Marcar como leídas"
    
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(read=False, read_at=None)
        self.message_user(request, f'{updated} notificación(es) marcada(s) como no leída(s)')
    mark_as_unread.short_description = "Marcar como no leídas"
