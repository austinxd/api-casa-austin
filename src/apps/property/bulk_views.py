
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
