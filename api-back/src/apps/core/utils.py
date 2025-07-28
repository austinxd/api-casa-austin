import csv, json
from django.http import HttpResponse, JsonResponse

from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.http import Http404

def custom_exception_handler(exc, context):
    if isinstance(exc, Http404):
        return Response({"detail": "El recurso no existe o no esta disponible para Ud."}, status=404)
    else:
        return exception_handler(exc, context)

class ExportCsvMixin:
    def export_as_csv(self, request, queryset):

        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename={}.csv'.format(meta)
        writer = csv.writer(response)

        writer.writerow(field_names)
        for obj in queryset:
            row = writer.writerow([getattr(obj, field) for field in field_names])

        return response

    export_as_csv.short_description = "Exportar CSV Seleccionados"

class ExportJsonMixin:
    def export_as_json(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        data = []
        for obj in queryset:
            item = {}
            for field_name in field_names:
                item[field_name] = str(getattr(obj, field_name))
            data.append(item)

        response_data = json.dumps(data, indent=4)
        response = JsonResponse(data, safe=False)
        response['Content-Disposition'] = 'attachment; filename={}.json'.format(meta)
        return response

    export_as_json.short_description = "Exportar JSON Seleccionados"