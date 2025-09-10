
from django.urls import path
from .views import BotDiscountListAPIView

urlpatterns = [
    path('discount-list/', BotDiscountListAPIView.as_view(), name='bot-discount-list'),
]
