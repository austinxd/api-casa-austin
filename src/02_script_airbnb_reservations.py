import os
import django
import logging
import pdb  # Para depuración interactiva

# Configuración del entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')  # Ajusta si es necesario
django.setup()  # Inicializa Django y carga las aplicaciones

# Importación de funciones y modelos
from apps.core.functions import confeccion_ics
from apps.property.models import Property
from apps.core.functions import update_air_bnb_api

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def get_airbnb_reservations():
    logging.info('Comenzando proceso para obtener propiedades de API de AirBnB')
    
    # Consultar propiedades con URL de Airbnb
    query_property = Property.objects.exclude(airbnb_url__isnull=True)
    logging.debug(f'Número de propiedades encontradas: {query_property.count()}')

    for q in query_property:
        try:
            if q.airbnb_url:
                # Registro de la propiedad procesada
                logging.debug(f'Procesando propiedad con ID: {q.id}, Nombre: {q.name}, URL: {q.airbnb_url}')
                
                # Depuración interactiva para inspeccionar
                pdb.set_trace()  # Detiene la ejecución aquí
                
                # Actualización de la propiedad a través de la API
                update_air_bnb_api(q)
        except Exception as e:
            logging.error(f'Error obteniendo datos de API Airbnb para la propiedad {q.id}: {e}')

    logging.info('Finalizando proceso para obtener propiedades de API de AirBnB')

if __name__ == "__main__":
    # Ejecutar sincronización con Airbnb
    get_airbnb_reservations()

    # Actualizar calendario ICS después de la sincronización
    try:
        logging.info('Iniciando actualización de calendario ICS')
        confeccion_ics()
    except Exception as e:
        logging.error(f'Error durante la actualización del calendario ICS: {e}')
