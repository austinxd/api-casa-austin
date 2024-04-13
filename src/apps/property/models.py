from django.db import models

from apps.core.models import BaseModel
from django.core.validators import MinValueValidator, MaxValueValidator



class Property(BaseModel):
    name = models.CharField(max_length=150, null=False, blank=False)
    location = models.CharField(max_length=250, null=True, blank=True)
    airbnb_url = models.URLField(null=True, blank=True)
    capacity_max = models.IntegerField(null=True, blank=True)
    background_color = models.CharField(max_length=255, null=False, blank=False, default="#fff")

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()

class ProfitPropertyAirBnb(BaseModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=False, blank=False)
    month = models.PositiveIntegerField(
        null=False, 
        blank=False, 
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ]
    )
    year = models.PositiveIntegerField(null=False, blank=False, default=1)
    profit_sol = models.DecimalField(max_digits=20, decimal_places=2, verbose_name='Ganancia (Soles)')
    
    class Meta:
        unique_together = ('property', 'month', 'year')

    def __str__(self):
        return f"Ganancia AirBnB {self.property.name} - Mes: {self.month} Año: {self.year}"