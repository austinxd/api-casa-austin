
from django import forms
from django.core.exceptions import ValidationError
from .models import Property
from .pricing_models import SpecialDatePricing
import csv
from io import StringIO


class BulkSpecialDateForm(forms.Form):
    property = forms.ModelChoiceField(
        queryset=Property.objects.filter(deleted=False),
        label="Propiedad",
        help_text="Selecciona la propiedad para la cual agregar fechas especiales"
    )
    
    bulk_data = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 10,
            'cols': 80,
            'placeholder': 'Formato: día,mes,descripción,precio_usd\nEjemplo:\n25,12,Navidad,150.00\n31,12,Año Nuevo,200.00\n1,1,Año Nuevo,180.00\n14,2,San Valentín,120.00'
        }),
        label="Fechas Especiales (CSV)",
        help_text="Ingresa una fecha por línea en formato: día,mes,descripción,precio_usd"
    )
    
    overwrite_existing = forms.BooleanField(
        required=False,
        initial=False,
        label="Sobrescribir fechas existentes",
        help_text="Si está marcado, actualizará las fechas que ya existen para esta propiedad"
    )
    
    def clean_bulk_data(self):
        data = self.cleaned_data['bulk_data']
        if not data.strip():
            raise ValidationError("Debes ingresar al menos una fecha especial")
        
        lines = data.strip().split('\n')
        parsed_dates = []
        errors = []
        
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
                
            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 4:
                errors.append(f"Línea {i}: Formato incorrecto. Debe ser: día,mes,descripción,precio_usd")
                continue
            
            try:
                day = int(parts[0])
                month = int(parts[1])
                description = parts[2]
                price = float(parts[3])
                
                # Validaciones
                if not (1 <= day <= 31):
                    errors.append(f"Línea {i}: Día debe estar entre 1 y 31")
                if not (1 <= month <= 12):
                    errors.append(f"Línea {i}: Mes debe estar entre 1 y 12")
                if not description:
                    errors.append(f"Línea {i}: La descripción no puede estar vacía")
                if price <= 0:
                    errors.append(f"Línea {i}: El precio debe ser mayor a 0")
                
                parsed_dates.append({
                    'day': day,
                    'month': month,
                    'description': description,
                    'price_usd': price
                })
                
            except ValueError as e:
                errors.append(f"Línea {i}: Error en formato de números - {e}")
        
        if errors:
            raise ValidationError(errors)
        
        if not parsed_dates:
            raise ValidationError("No se encontraron fechas válidas para procesar")
        
        return parsed_dates
    
    def save(self):
        property_obj = self.cleaned_data['property']
        dates_data = self.cleaned_data['bulk_data']
        overwrite = self.cleaned_data['overwrite_existing']
        
        created_count = 0
        updated_count = 0
        
        for date_info in dates_data:
            special_date, created = SpecialDatePricing.objects.get_or_create(
                property=property_obj,
                day=date_info['day'],
                month=date_info['month'],
                defaults={
                    'description': date_info['description'],
                    'price_usd': date_info['price_usd'],
                    'is_active': True
                }
            )
            
            if created:
                created_count += 1
            elif overwrite:
                special_date.description = date_info['description']
                special_date.price_usd = date_info['price_usd']
                special_date.is_active = True
                special_date.save()
                updated_count += 1
        
        return created_count, updated_count


class CSVUploadForm(forms.Form):
    property = forms.ModelChoiceField(
        queryset=Property.objects.filter(deleted=False),
        label="Propiedad",
        help_text="Selecciona la propiedad para la cual agregar fechas especiales"
    )
    
    csv_file = forms.FileField(
        label="Archivo CSV",
        help_text="Sube un archivo CSV con columnas: día,mes,descripción,precio_usd"
    )
    
    overwrite_existing = forms.BooleanField(
        required=False,
        initial=False,
        label="Sobrescribir fechas existentes",
        help_text="Si está marcado, actualizará las fechas que ya existen para esta propiedad"
    )
    
    def clean_csv_file(self):
        file = self.cleaned_data['csv_file']
        if not file.name.endswith('.csv'):
            raise ValidationError("El archivo debe ser un CSV")
        
        try:
            content = file.read().decode('utf-8')
            file.seek(0)  # Reset file pointer
            
            reader = csv.reader(StringIO(content))
            parsed_dates = []
            errors = []
            
            for i, row in enumerate(reader, 1):
                if len(row) != 4:
                    errors.append(f"Fila {i}: Debe tener 4 columnas (día,mes,descripción,precio_usd)")
                    continue
                
                try:
                    day = int(row[0].strip())
                    month = int(row[1].strip())
                    description = row[2].strip()
                    price = float(row[3].strip())
                    
                    # Validaciones
                    if not (1 <= day <= 31):
                        errors.append(f"Fila {i}: Día debe estar entre 1 y 31")
                    if not (1 <= month <= 12):
                        errors.append(f"Fila {i}: Mes debe estar entre 1 y 12")
                    if not description:
                        errors.append(f"Fila {i}: La descripción no puede estar vacía")
                    if price <= 0:
                        errors.append(f"Fila {i}: El precio debe ser mayor a 0")
                    
                    parsed_dates.append({
                        'day': day,
                        'month': month,
                        'description': description,
                        'price_usd': price
                    })
                    
                except ValueError as e:
                    errors.append(f"Fila {i}: Error en formato - {e}")
            
            if errors:
                raise ValidationError(errors)
            
            if not parsed_dates:
                raise ValidationError("No se encontraron fechas válidas en el archivo")
            
            return parsed_dates
            
        except Exception as e:
            raise ValidationError(f"Error procesando archivo CSV: {e}")
