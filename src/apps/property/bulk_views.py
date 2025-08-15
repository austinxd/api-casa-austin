
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .forms import BulkSpecialDateForm, CSVUploadForm
from .models import Property
from .pricing_models import SpecialDatePricing
import json


@method_decorator(staff_member_required, name='dispatch')
class PropertySpecialDatesView(View):
    template_name = 'admin/property/property_special_dates.html'
    
    def get(self, request, property_id=None):
        if property_id:
            property_obj = get_object_or_404(Property, id=property_id, deleted=False)
            special_dates = SpecialDatePricing.objects.filter(
                property=property_obj, 
                deleted=False
            ).order_by('month', 'day')
        else:
            property_obj = None
            special_dates = []
        
        properties = Property.objects.filter(deleted=False).order_by('name')
        
        # Crear datos para el formulario
        special_dates_data = []
        for sd in special_dates:
            special_dates_data.append({
                'id': sd.id,
                'month': sd.month,
                'day': sd.day,
                'description': sd.description,
                'price_usd': float(sd.price_usd),
                'is_active': sd.is_active
            })
        
        return render(request, self.template_name, {
            'property': property_obj,
            'properties': properties,
            'special_dates': special_dates_data,
            'title': f'Gestionar Fechas Especiales - {property_obj.name}' if property_obj else 'Seleccionar Propiedad'
        })
    
    def post(self, request, property_id=None):
        if not property_id:
            messages.error(request, 'Debe seleccionar una propiedad')
            return redirect('property:special-dates-manager')
        
        property_obj = get_object_or_404(Property, id=property_id, deleted=False)
        
        try:
            # Procesar datos del formulario
            dates_data = json.loads(request.POST.get('dates_data', '[]'))
            
            # Eliminar fechas existentes para esta propiedad
            SpecialDatePricing.objects.filter(property=property_obj).delete()
            
            # Crear nuevas fechas
            created_count = 0
            for date_info in dates_data:
                if date_info.get('description') and date_info.get('price_usd'):
                    SpecialDatePricing.objects.create(
                        property=property_obj,
                        month=int(date_info['month']),
                        day=int(date_info['day']),
                        description=date_info['description'],
                        price_usd=float(date_info['price_usd']),
                        is_active=date_info.get('is_active', True)
                    )
                    created_count += 1
            
            messages.success(request, f'Se guardaron {created_count} fechas especiales exitosamente')
            return redirect('property:special-dates-manager', property_id=property_id)
            
        except Exception as e:
            messages.error(request, f'Error al guardar: {e}')
            return self.get(request, property_id)


@method_decorator(staff_member_required, name='dispatch')


from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views import View
from .forms import BulkSpecialDateForm, CSVUploadForm


@method_decorator(staff_member_required, name='dispatch')
class BulkSpecialDateView(View):
    template_name = 'admin/property/bulk_special_dates.html'
    
    def get(self, request):
        form = BulkSpecialDateForm()
        csv_form = CSVUploadForm()
        return render(request, self.template_name, {
            'form': form,
            'csv_form': csv_form,
            'title': 'Agregar Fechas Especiales Masivamente'
        })
    
    def post(self, request):
        if 'bulk_submit' in request.POST:
            return self.handle_bulk_form(request)
        elif 'csv_submit' in request.POST:
            return self.handle_csv_form(request)
        
        return self.get(request)
    
    def handle_bulk_form(self, request):
        form = BulkSpecialDateForm(request.POST)
        csv_form = CSVUploadForm()
        
        if form.is_valid():
            try:
                created, updated = form.save()
                messages.success(
                    request, 
                    f'Fechas especiales procesadas exitosamente: {created} creadas, {updated} actualizadas'
                )
                return redirect('admin:property_specialdatepricing_changelist')
            except Exception as e:
                messages.error(request, f'Error al guardar: {e}')
        
        return render(request, self.template_name, {
            'form': form,
            'csv_form': csv_form,
            'title': 'Agregar Fechas Especiales Masivamente'
        })
    
    def handle_csv_form(self, request):
        csv_form = CSVUploadForm(request.POST, request.FILES)
        form = BulkSpecialDateForm()
        
        if csv_form.is_valid():
            try:
                property_obj = csv_form.cleaned_data['property']
                dates_data = csv_form.cleaned_data['csv_file']
                overwrite = csv_form.cleaned_data['overwrite_existing']
                
                created_count = 0
                updated_count = 0
                
                from .pricing_models import SpecialDatePricing
                
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
                
                messages.success(
                    request, 
                    f'CSV procesado exitosamente: {created_count} fechas creadas, {updated_count} actualizadas'
                )
                return redirect('admin:property_specialdatepricing_changelist')
                
            except Exception as e:
                messages.error(request, f'Error al procesar CSV: {e}')
        
        return render(request, self.template_name, {
            'form': form,
            'csv_form': csv_form,
            'title': 'Agregar Fechas Especiales Masivamente'
        })
