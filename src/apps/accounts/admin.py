from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser

from django.contrib.admin.models import LogEntry


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

    fieldsets = UserAdmin.fieldsets + (
        ('Extra data', {'fields': ('profile_photo',)}),
    )

    def grupo_rol(self, obj):
        return obj.groups.all().first()

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(LogEntry)
