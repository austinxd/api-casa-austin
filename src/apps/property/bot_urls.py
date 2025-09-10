
from django.urls import path
from .views import BotGlobalDiscountAPIView

urlpatterns = [
    path('global-discount/', BotGlobalDiscountAPIView.as_view(), name='bot-global-discount'),
]
