from django.contrib import admin
from .models import Reservation, RentalReceipt


admin.site.register(Reservation)
admin.site.register(RentalReceipt)
