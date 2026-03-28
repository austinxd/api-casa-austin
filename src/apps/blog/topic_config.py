"""
Templates de temas para generación de blog posts.

Funciona como fallback cuando no hay datos de Search Console,
o como complemento para diversificar el contenido.
"""
import random
from datetime import date


# Templates organizados por categoría
TOPIC_TEMPLATES = {
    'property': {
        'weight': 25,
        'needs_property': True,
        'image_source': 'property',
        'templates': [
            {
                'key': 'property_spotlight',
                'title_hint': 'Descubre {property_name}: Tu Casa Ideal en {location}',
                'description': 'Post destacando una propiedad específica con sus amenities, '
                               'capacidad, fotos y experiencias que ofrece.',
                'keywords': ['alquiler casa {location}', 'casa vacacional {location}',
                             '{property_name} alquiler'],
            },
            {
                'key': 'property_experience',
                'title_hint': 'Cómo es hospedarte en {property_name}',
                'description': 'Narrativa de la experiencia de un huésped típico, '
                               'desde el check-in hasta el check-out.',
                'keywords': ['experiencia alquiler {location}', 'hospedaje {location}'],
            },
            {
                'key': 'property_comparison',
                'title_hint': '¿Cuál Casa Austin elegir para tu viaje?',
                'description': 'Comparación de propiedades según tipo de viaje: '
                               'familia, pareja, grupo de amigos.',
                'keywords': ['mejor casa alquiler playa lima', 'comparar casas vacaciones lima'],
            },
        ],
    },
    'lima_travel': {
        'weight': 15,
        'needs_property': False,
        'image_source': 'dalle',
        'templates': [
            {
                'key': 'lima_guide',
                'title_hint': 'Guía Completa: Qué Hacer en Lima Sur',
                'description': 'Guía de actividades, restaurantes y atracciones '
                               'cerca de las propiedades de Casa Austin.',
                'keywords': ['qué hacer en lima sur', 'turismo lima sur',
                             'actividades punta hermosa'],
            },
            {
                'key': 'lima_hidden_gems',
                'title_hint': 'Lugares Secretos de Lima Sur que Debes Conocer',
                'description': 'Descubrimientos poco conocidos en las playas del sur de Lima.',
                'keywords': ['lugares secretos lima sur', 'playas escondidas lima'],
            },
            {
                'key': 'lima_transport',
                'title_hint': 'Cómo Llegar a las Playas del Sur de Lima',
                'description': 'Guía de transporte desde Lima centro/aeropuerto '
                               'hasta Punta Hermosa y alrededores.',
                'keywords': ['cómo llegar punta hermosa', 'transporte playas sur lima'],
            },
        ],
    },
    'beaches': {
        'weight': 15,
        'needs_property': False,
        'image_source': 'dalle',
        'templates': [
            {
                'key': 'beach_guide',
                'title_hint': 'Las Mejores Playas del Sur de Lima: Guía Definitiva',
                'description': 'Ranking y descripción de las mejores playas '
                               'desde Punta Hermosa hasta Asia.',
                'keywords': ['mejores playas lima', 'playas sur de lima',
                             'playas punta hermosa'],
            },
            {
                'key': 'surf_guide',
                'title_hint': 'Guía de Surf en Punta Hermosa y Alrededores',
                'description': 'Spots de surf, condiciones ideales, escuelas y '
                               'dónde hospedarse para surfistas.',
                'keywords': ['surf punta hermosa', 'escuelas surf lima',
                             'mejores olas lima'],
            },
            {
                'key': 'beach_activities',
                'title_hint': 'Actividades Acuáticas en las Playas del Sur de Lima',
                'description': 'Surf, paddleboard, kayak, snorkel y más '
                               'en las playas cercanas a Casa Austin.',
                'keywords': ['actividades playa lima', 'deportes acuáticos lima sur'],
            },
        ],
    },
    'seasonal': {
        'weight': 15,
        'needs_property': True,
        'image_source': 'property',
        'templates': [
            {
                'key': 'summer_escape',
                'title_hint': 'Verano en Lima: Las Mejores Casas de Playa para Alquilar',
                'description': 'Guía de verano (dic-mar) con propiedades ideales '
                               'para la temporada de playa.',
                'keywords': ['casa playa verano lima', 'alquiler verano playa lima'],
                'months': [11, 12, 1, 2, 3],
            },
            {
                'key': 'winter_retreat',
                'title_hint': 'Escapada de Invierno: Casas con Piscina Temperada en Lima Sur',
                'description': 'Por qué visitar la playa en invierno: tranquilidad, '
                               'precios, piscinas temperadas.',
                'keywords': ['casa playa invierno lima', 'piscina temperada lima sur'],
                'months': [5, 6, 7, 8, 9],
            },
            {
                'key': 'fiestas_patrias',
                'title_hint': 'Fiestas Patrias en la Playa: Alquila tu Casa en Lima Sur',
                'description': 'Planes para el feriado largo de julio '
                               'en las casas de Casa Austin.',
                'keywords': ['fiestas patrias playa lima', 'feriado largo julio casa playa'],
                'months': [6, 7],
            },
            {
                'key': 'new_year',
                'title_hint': 'Año Nuevo en la Playa: Celebra en una Casa Frente al Mar',
                'description': 'Celebración de año nuevo en las playas del sur de Lima.',
                'keywords': ['año nuevo playa lima', 'casa playa año nuevo'],
                'months': [11, 12, 1],
            },
            {
                'key': 'semana_santa',
                'title_hint': 'Semana Santa en la Playa: Descansa en Casa Austin',
                'description': 'Feriado de Semana Santa ideal para una escapada a la playa.',
                'keywords': ['semana santa playa lima', 'feriado semana santa casa playa'],
                'months': [3, 4],
            },
        ],
    },
    'tips': {
        'weight': 10,
        'needs_property': False,
        'image_source': 'dalle',
        'templates': [
            {
                'key': 'packing_guide',
                'title_hint': 'Qué Llevar a tu Casa de Playa: Lista Completa',
                'description': 'Checklist de lo que necesitas para un viaje '
                               'a una casa de playa alquilada.',
                'keywords': ['qué llevar playa', 'lista viaje playa',
                             'equipaje casa playa'],
            },
            {
                'key': 'rental_tips',
                'title_hint': 'Consejos para Alquilar una Casa de Playa en Lima',
                'description': 'Tips para elegir, reservar y disfrutar '
                               'una casa de playa alquilada.',
                'keywords': ['consejos alquilar casa playa', 'tips alquiler playa lima'],
            },
            {
                'key': 'save_money',
                'title_hint': 'Cómo Ahorrar al Alquilar una Casa de Playa',
                'description': 'Estrategias para conseguir mejores precios: '
                               'temporada baja, grupos, reserva anticipada.',
                'keywords': ['ahorrar alquiler playa', 'casa playa barata lima'],
            },
        ],
    },
    'events': {
        'weight': 5,
        'needs_property': True,
        'image_source': 'property',
        'templates': [
            {
                'key': 'birthday_party',
                'title_hint': 'Celebra tu Cumpleaños en una Casa de Playa en Lima',
                'description': 'Ideas para fiestas de cumpleaños en las propiedades '
                               'de Casa Austin.',
                'keywords': ['cumpleaños casa playa lima', 'fiesta playa alquiler'],
            },
            {
                'key': 'corporate_retreat',
                'title_hint': 'Retiros Corporativos en Casa Austin',
                'description': 'Cómo organizar un team building o retiro '
                               'de empresa en la playa.',
                'keywords': ['retiro corporativo playa lima', 'team building playa'],
            },
        ],
    },
    'gastronomy': {
        'weight': 10,
        'needs_property': False,
        'image_source': 'dalle',
        'templates': [
            {
                'key': 'restaurants_guide',
                'title_hint': 'Los Mejores Restaurantes cerca de Punta Hermosa',
                'description': 'Guía gastronómica de restaurantes y huariques '
                               'en las playas del sur de Lima.',
                'keywords': ['restaurantes punta hermosa', 'dónde comer playa lima sur'],
            },
            {
                'key': 'ceviche_guide',
                'title_hint': 'Dónde Comer el Mejor Ceviche en las Playas del Sur de Lima',
                'description': 'Los mejores cevicherías y restaurantes de mariscos '
                               'cerca de las propiedades.',
                'keywords': ['ceviche punta hermosa', 'cevichería playa lima'],
            },
            {
                'key': 'cooking_at_beach',
                'title_hint': 'Recetas para Preparar en tu Casa de Playa',
                'description': 'Ideas de comidas fáciles y ricas para cocinar '
                               'durante tu estadía en la playa.',
                'keywords': ['recetas casa playa', 'cocinar en la playa'],
            },
        ],
    },
    'family': {
        'weight': 5,
        'needs_property': True,
        'image_source': 'property',
        'templates': [
            {
                'key': 'family_vacation',
                'title_hint': 'Vacaciones en Familia: Casas de Playa para Todos',
                'description': 'Propiedades ideales para familias con niños, '
                               'actividades y tips de seguridad.',
                'keywords': ['casa playa familia lima', 'vacaciones familia playa'],
            },
            {
                'key': 'kids_activities',
                'title_hint': 'Actividades para Niños en las Playas del Sur de Lima',
                'description': 'Qué hacer con niños en Punta Hermosa y alrededores.',
                'keywords': ['actividades niños playa lima', 'playa con niños lima'],
            },
        ],
    },
}


def _get_current_season():
    """Determina la temporada actual (hemisferio sur, Lima)."""
    month = date.today().month
    if month in [12, 1, 2, 3]:
        return 'summer'
    elif month in [4, 5]:
        return 'autumn'
    elif month in [6, 7, 8, 9]:
        return 'winter'
    else:
        return 'spring'


def _is_template_in_season(template):
    """Verifica si un template estacional aplica al mes actual."""
    months = template.get('months')
    if not months:
        return True
    return date.today().month in months


class TopicRotator:
    """Selecciona el siguiente tema evitando repetición."""

    def __init__(self):
        from apps.blog.models import BlogTopicPlan
        self.recent_topics = list(
            BlogTopicPlan.objects.order_by('-generated_at')[:20]
            .values_list('topic_key', flat=True)
        )

    def get_next_topic(self, force_type=None):
        """
        Selecciona un tema ponderado por peso, evitando repetición.

        Args:
            force_type: Forzar un tipo de tema específico (e.g., 'property', 'beaches')

        Returns:
            dict con topic_type, template, image_source, needs_property
        """
        if force_type and force_type in TOPIC_TEMPLATES:
            categories = {force_type: TOPIC_TEMPLATES[force_type]}
        else:
            categories = TOPIC_TEMPLATES

        # Construir lista de candidatos con pesos
        candidates = []
        for topic_type, config in categories.items():
            weight = config['weight']
            for template in config['templates']:
                # Saltar si se usó recientemente
                if template['key'] in self.recent_topics:
                    continue

                # Saltar templates estacionales fuera de temporada
                if not _is_template_in_season(template):
                    continue

                # Boost estacional: si es verano y el template es de verano, +50% peso
                season = _get_current_season()
                effective_weight = weight
                if season == 'summer' and topic_type in ('beaches', 'seasonal'):
                    effective_weight = int(weight * 1.5)
                elif season == 'winter' and template.get('key') == 'winter_retreat':
                    effective_weight = int(weight * 2)

                candidates.append({
                    'topic_type': topic_type,
                    'template': template,
                    'image_source': config['image_source'],
                    'needs_property': config['needs_property'],
                    'weight': effective_weight,
                })

        if not candidates:
            # Fallback: si todos se usaron, resetear y elegir cualquiera
            for topic_type, config in categories.items():
                for template in config['templates']:
                    if _is_template_in_season(template):
                        candidates.append({
                            'topic_type': topic_type,
                            'template': template,
                            'image_source': config['image_source'],
                            'needs_property': config['needs_property'],
                            'weight': config['weight'],
                        })

        if not candidates:
            # Último fallback
            config = TOPIC_TEMPLATES['property']
            template = config['templates'][0]
            return {
                'topic_type': 'property',
                'template': template,
                'image_source': 'property',
                'needs_property': True,
                'weight': 25,
            }

        # Selección ponderada
        weights = [c['weight'] for c in candidates]
        selected = random.choices(candidates, weights=weights, k=1)[0]
        return selected
