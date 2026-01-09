from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser

from django.contrib.admin.models import LogEntry

# JWT Token Blacklist
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    
    list_display = (
        'username',
        'last_name',
        'first_name',
        'is_staff',
        'grupo_rol'
        )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'first_name',
                'last_name',
                'email',
                'profile_photo',
                'password1',
                'password2',
                'groups',
            ),
        }),
    )

    fieldsets = UserAdmin.fieldsets + (
        ('Extra data', {'fields': ('profile_photo',)}),
    )

    def grupo_rol(self, obj):
        return obj.groups.all().first()

class LogAdmin(admin.ModelAdmin):
    model = LogEntry

    list_display = (
        'action_time',
        'object_repr',
    )

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(LogEntry, LogAdmin)


# ============================================
# JWT TOKEN BLACKLIST ADMIN
# ============================================

class OutstandingTokenAdmin(admin.ModelAdmin):
    """Admin para ver tokens JWT activos/emitidos"""
    list_display = ('jti', 'user', 'created_at', 'expires_at', 'is_blacklisted')
    list_filter = ('user', 'created_at', 'expires_at')
    search_fields = ('user__username', 'user__email', 'jti')
    ordering = ('-created_at',)
    readonly_fields = ('jti', 'token', 'created_at', 'expires_at', 'user')

    def is_blacklisted(self, obj):
        """Verificar si el token está en blacklist"""
        return BlacklistedToken.objects.filter(token=obj).exists()
    is_blacklisted.boolean = True
    is_blacklisted.short_description = "Bloqueado"


class BlacklistedTokenAdmin(admin.ModelAdmin):
    """Admin para ver tokens JWT bloqueados"""
    list_display = ('token_jti', 'token_user', 'blacklisted_at', 'token_expires_at')
    list_filter = ('blacklisted_at',)
    search_fields = ('token__user__username', 'token__user__email', 'token__jti')
    ordering = ('-blacklisted_at',)
    readonly_fields = ('token', 'blacklisted_at')

    def token_jti(self, obj):
        return obj.token.jti
    token_jti.short_description = "Token JTI"

    def token_user(self, obj):
        return obj.token.user
    token_user.short_description = "Usuario"

    def token_expires_at(self, obj):
        return obj.token.expires_at
    token_expires_at.short_description = "Expira"


# Desregistrar si ya estaban registrados por defecto
try:
    admin.site.unregister(OutstandingToken)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(BlacklistedToken)
except admin.sites.NotRegistered:
    pass

# Registrar con nuestros admins personalizados
admin.site.register(OutstandingToken, OutstandingTokenAdmin)
admin.site.register(BlacklistedToken, BlacklistedTokenAdmin)
