from django.contrib import admin
from .models import Reservation, RentalReceipt

class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "property",
        "check_in_date",
        "check_out_date",
        "origin",
        "deleted"
    )


admin.site.register(Reservation, ReservationAdmin)
admin.site.register(RentalReceipt)
