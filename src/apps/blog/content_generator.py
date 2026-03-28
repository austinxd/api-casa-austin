"""
Generador de blog posts con IA (Claude) + datos de Search Console.

Flujo:
1. Consulta datos de Search Console (cacheados) para keywords con oportunidad
2. Claude analiza keywords + datos de propiedades + posts existentes → elige tema
3. Claude genera: título, HTML content, excerpt, meta_description
4. Selecciona imagen (foto de propiedad o DALL-E)
5. Crea BlogPost como draft + registra en BlogTopicPlan
"""
import json
import logging
import random
from datetime import date
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger('apps')


class BlogContentGenerator:
    """Orquestador principal de generación de blog posts."""

    def __init__(self):
        self.openai_key = getattr(settings, 'OPENAI_API_KEY', '')

    def generate(self, dry_run=False, force_topic_type=None, force_keyword=None,
                 use_search_console=True):
        """
        Genera un blog post completo como borrador.

        Args:
            dry_run: Si True, muestra el plan sin crear nada
            force_topic_type: Forzar un tipo de tema (e.g., 'property')
            force_keyword: Forzar una keyword específica
            use_search_console: Si usar datos de Search Console

        Returns:
            dict con info del post generado (o plan en dry_run)
        """
        from apps.blog.models import BlogPost

        logger.info("Iniciando generación de blog post...")

        # 1. Obtener datos de contexto
        properties_data = self._get_properties_data()
        existing_posts = self._get_existing_posts()

        # 2. Determinar keyword/tema
        keyword_data = None
        if force_keyword:
            keyword_data = {
                'query': force_keyword,
                'clicks': 0,
                'impressions': 0,
                'ctr': 0,
                'position': 0,
                'source': 'manual',
            }
        elif use_search_console:
            keyword_data = self._analyze_keywords(existing_posts)

        # 3. Seleccionar tema/template
        topic = self._select_topic(
            keyword_data=keyword_data,
            force_type=force_topic_type,
            properties_data=properties_data,
        )

        # 4. Seleccionar propiedad si el tema lo requiere
        selected_property = None
        if topic['needs_property']:
            selected_property = self._select_property(properties_data)

        logger.info(
            f"Tema seleccionado: [{topic['topic_type']}] {topic['template']['key']} "
            f"| Keyword: {keyword_data['query'] if keyword_data else 'N/A'}"
        )

        if dry_run:
            return self._format_dry_run(topic, keyword_data, selected_property, existing_posts)

        # 5. Generar contenido con Claude
        system_prompt = self._build_system_prompt(properties_data)
        generation_prompt = self._build_generation_prompt(
            topic=topic,
            keyword_data=keyword_data,
            selected_property=selected_property,
            existing_posts=existing_posts,
        )

        response = self._call_llm(system_prompt, generation_prompt)
        parsed = self._parse_response(response)

        # 6. Manejar imagen
        image_file = self._handle_image(topic, selected_property)

        # 7. Crear blog post como draft
        blog_post = self._create_blog_post(parsed, image_file)

        # 8. Registrar en BlogTopicPlan
        self._create_topic_plan(topic, keyword_data, blog_post)

        logger.info(f"Blog post generado: '{blog_post.title}' (draft)")

        return {
            'status': 'created',
            'post_id': str(blog_post.id),
            'title': blog_post.title,
            'slug': blog_post.slug,
            'topic_type': topic['topic_type'],
            'keyword': keyword_data['query'] if keyword_data else None,
            'has_image': bool(image_file),
        }

    def _get_properties_data(self):
        """Obtiene datos reales de todas las propiedades activas."""
        from apps.property.models import Property

        properties = Property.objects.filter(deleted=False)
        data = []
        for prop in properties:
            photos = prop.photos.filter(deleted=False).order_by('order')
            main_photo = photos.filter(is_main=True).first() or photos.first()

            data.append({
                'id': str(prop.id),
                'name': prop.name,
                'titulo': prop.titulo or '',
                'descripcion': prop.descripcion or '',
                'location': prop.location or '',
                'capacity_max': prop.capacity_max or 0,
                'dormitorios': prop.dormitorios or 0,
                'banos': prop.banos or 0,
                'precio_desde': float(prop.precio_desde) if prop.precio_desde else 0,
                'caracteristicas': prop.caracteristicas or [],
                'airbnb_url': prop.airbnb_url or '',
                'slug': prop.slug or '',
                'main_photo_url': main_photo.get_image_url() if main_photo else None,
                'main_photo_obj': main_photo,
                'photo_count': photos.count(),
            })

        return data

    def _get_existing_posts(self):
        """Obtiene títulos y slugs de posts existentes para evitar duplicados."""
        from apps.blog.models import BlogPost

        return list(
            BlogPost.objects.filter(deleted=False)
            .order_by('-published_date')[:30]
            .values('title', 'slug', 'category__name')
        )

    def _analyze_keywords(self, existing_posts):
        """
        Analiza datos de Search Console cacheados y elige la mejor keyword.
        Prioriza keywords no cubiertas por posts existentes.
        """
        from apps.blog.search_console import SearchConsoleClient

        opportunities = SearchConsoleClient.get_cached_opportunities()

        if not opportunities:
            logger.info("No hay datos de Search Console cacheados. Usando solo templates.")
            return None

        # Filtrar keywords ya cubiertas por posts existentes
        existing_slugs = {p['slug'] for p in existing_posts}
        existing_titles_lower = {p['title'].lower() for p in existing_posts}

        scored_keywords = []
        for opp in opportunities:
            query = opp.query if hasattr(opp, 'query') else opp['query']
            query_lower = query.lower()

            # Penalizar si ya hay un post con palabras muy similares
            already_covered = any(
                query_lower in title or title in query_lower
                for title in existing_titles_lower
            )

            impressions = opp.impressions if hasattr(opp, 'impressions') else opp['impressions']
            position = opp.position if hasattr(opp, 'position') else opp['position']
            ctr = opp.ctr if hasattr(opp, 'ctr') else opp['ctr']

            # Score: impresiones altas + posición media = más oportunidad
            score = impressions * (1 - ctr / 100) * (50 - position) / 50
            if already_covered:
                score *= 0.1  # Fuerte penalización

            scored_keywords.append({
                'query': query,
                'clicks': opp.clicks if hasattr(opp, 'clicks') else opp['clicks'],
                'impressions': impressions,
                'ctr': ctr,
                'position': position,
                'score': score,
                'source': 'search_console',
            })

        if not scored_keywords:
            return None

        # Elegir top keyword (con algo de aleatoriedad en top 5)
        scored_keywords.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = scored_keywords[:5]
        selected = random.choice(top_candidates)

        logger.info(
            f"Keyword seleccionada: '{selected['query']}' "
            f"(imp={selected['impressions']}, pos={selected['position']}, score={selected['score']:.1f})"
        )

        return selected

    def _select_topic(self, keyword_data=None, force_type=None, properties_data=None):
        """Selecciona el tema/template para el post."""
        from apps.blog.topic_config import TopicRotator

        if keyword_data and keyword_data.get('source') == 'search_console':
            # Si tenemos una keyword de Search Console, usar template genérico de SC
            query = keyword_data['query'].lower()

            # Determinar el tipo de tema basado en la keyword
            if any(w in query for w in ['casa', 'alquiler', 'hospedaje', 'hotel']):
                topic_type = 'property'
            elif any(w in query for w in ['playa', 'surf', 'ola', 'arena']):
                topic_type = 'beaches'
            elif any(w in query for w in ['comer', 'restaurante', 'ceviche', 'comida']):
                topic_type = 'gastronomy'
            elif any(w in query for w in ['niño', 'familia', 'hijo', 'kid']):
                topic_type = 'family'
            elif any(w in query for w in ['lima', 'turismo', 'visitar', 'conocer']):
                topic_type = 'lima_travel'
            else:
                topic_type = 'tips'

            from apps.blog.topic_config import TOPIC_TEMPLATES
            config = TOPIC_TEMPLATES.get(topic_type, TOPIC_TEMPLATES['tips'])

            return {
                'topic_type': 'search_console',
                'template': {
                    'key': f"sc_{keyword_data['query'][:50].replace(' ', '_')}",
                    'title_hint': '',  # Claude decidirá
                    'description': f"Post optimizado para la keyword: {keyword_data['query']}",
                    'keywords': [keyword_data['query']],
                },
                'image_source': config['image_source'],
                'needs_property': config['needs_property'],
            }

        # Sin keyword de SC → usar rotador de templates
        rotator = TopicRotator()
        return rotator.get_next_topic(force_type=force_type)

    def _select_property(self, properties_data):
        """Selecciona una propiedad para el post (evitando repetición)."""
        from apps.blog.models import BlogTopicPlan

        if not properties_data:
            return None

        # Ver qué propiedades se usaron recientemente
        recent_property_names = set(
            BlogTopicPlan.objects.filter(
                topic_type='property',
            ).order_by('-generated_at')[:5]
            .values_list('topic_key', flat=True)
        )

        # Preferir propiedades no usadas recientemente
        available = [p for p in properties_data if p['name'] not in recent_property_names]
        if not available:
            available = properties_data

        return random.choice(available)

    def _build_system_prompt(self, properties_data):
        """Construye el system prompt con identidad de marca y datos reales."""
        season = self._get_season_context()

        properties_info = ""
        for p in properties_data:
            features = ", ".join(p['caracteristicas'][:10]) if p['caracteristicas'] else "N/A"
            properties_info += (
                f"- **{p['name']}** ({p['location']}): "
                f"{p['dormitorios']} dormitorios, {p['banos']} baños, "
                f"hasta {p['capacity_max']} huéspedes. "
                f"Desde S/{p['precio_desde']:.0f}/noche. "
                f"Amenities: {features}\n"
            )

        return f"""Eres un redactor SEO experto para Casa Austin, empresa de alquiler de casas
vacacionales de lujo en las playas del sur de Lima, Perú.

## Tu identidad
- Escribes en español peruano, tono profesional pero cercano
- Conoces perfectamente las propiedades de Casa Austin
- Eres experto en SEO on-page y contenido optimizado para búsquedas
- NUNCA inventas datos de propiedades — solo usas la información proporcionada

## Propiedades reales de Casa Austin
{properties_info}

## Contexto temporal
{season}

## Reglas de formato HTML
- Usa H2 y H3 para estructura (NUNCA H1, el título va aparte)
- Usa <ul>/<ol> para listas, <strong> para énfasis
- NO uses CSS inline ni clases (el blog usa Tailwind prose)
- Incluye enlaces internos a https://casaaustin.pe y sus secciones:
  - /casas-alquiler-punta-hermosa (listado de propiedades)
  - /blog (blog principal)
- El contenido debe tener entre 800-1500 palabras
- Párrafos cortos (3-4 líneas máximo)
- Incluye al menos un CTA hacia las propiedades

## Formato de respuesta
Responde ÚNICAMENTE con un JSON válido (sin markdown code blocks):
{{
  "title": "Título optimizado con keyword (50-70 caracteres)",
  "content": "<h2>...</h2><p>...</p>... (HTML completo del post)",
  "excerpt": "Resumen atractivo de 1-2 oraciones (max 200 caracteres)",
  "meta_description": "Meta description para Google (max 155 caracteres, incluye keyword)"
}}"""

    def _build_generation_prompt(self, topic, keyword_data, selected_property, existing_posts):
        """Construye el prompt específico para generar el post."""
        parts = []

        # Keyword target
        if keyword_data:
            parts.append(f"""## Keyword objetivo
- **Keyword**: {keyword_data['query']}
- **Impresiones**: {keyword_data.get('impressions', 'N/A')}
- **Posición actual**: {keyword_data.get('position', 'N/A')}
- **CTR actual**: {keyword_data.get('ctr', 'N/A')}%

La keyword debe aparecer naturalmente en: título, primer párrafo, al menos 2 subtítulos H2,
y en la meta description. Densidad natural, NO keyword stuffing.""")

        # Tema/template
        parts.append(f"""## Tema a desarrollar
- **Tipo**: {topic['topic_type']}
- **Descripción**: {topic['template']['description']}
- **Keywords sugeridas**: {', '.join(topic['template'].get('keywords', []))}""")

        if topic['template'].get('title_hint'):
            parts.append(f"- **Sugerencia de título**: {topic['template']['title_hint']}")

        # Propiedad seleccionada
        if selected_property:
            features = ", ".join(selected_property['caracteristicas'][:10]) \
                if selected_property['caracteristicas'] else "N/A"
            parts.append(f"""## Propiedad destacada en este post
- **Nombre**: {selected_property['name']}
- **Ubicación**: {selected_property['location']}
- **Capacidad**: {selected_property['capacity_max']} huéspedes
- **Dormitorios**: {selected_property['dormitorios']} | Baños: {selected_property['banos']}
- **Precio desde**: S/{selected_property['precio_desde']:.0f}/noche
- **Amenities**: {features}
- **URL Airbnb**: {selected_property['airbnb_url'] or 'N/A'}

Menciona esta propiedad de forma natural en el contenido, con datos reales.""")

        # Posts existentes (evitar duplicados)
        if existing_posts:
            titles = [f"- {p['title']}" for p in existing_posts[:20]]
            parts.append(f"""## Posts existentes (NO repetir temas)
{chr(10).join(titles)}

Asegúrate de que tu post sea diferente y complementario a los existentes.""")

        # URLs internas para enlazar
        parts.append("""## URLs internas para enlazar
- https://casaaustin.pe/casas-alquiler-punta-hermosa (listado de casas)
- https://casaaustin.pe/blog (blog)
- https://casaaustin.pe (home)

Incluye al menos 2 enlaces internos de forma natural en el contenido.""")

        return "\n\n".join(parts)

    def _call_llm(self, system_prompt, user_prompt):
        """Llama a la API de OpenAI (GPT-4o) para generar contenido."""
        if not self.openai_key:
            raise ValueError(
                "OPENAI_API_KEY no está configurado. "
                "Agrega tu API key de OpenAI al .env"
            )

        import openai

        client = openai.OpenAI(api_key=self.openai_key)

        logger.info("Llamando a OpenAI API para generar contenido...")

        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        response_text = response.choices[0].message.content
        logger.info(f"Respuesta recibida de OpenAI ({response.usage.prompt_tokens} in, "
                     f"{response.usage.completion_tokens} out)")

        return response_text

    def _parse_response(self, response_text):
        """Extrae el JSON de la respuesta de Claude."""
        text = response_text.strip()

        # Limpiar markdown code blocks si los hay
        if text.startswith('```'):
            lines = text.split('\n')
            # Remover primera y última línea (```json y ```)
            lines = [l for l in lines if not l.strip().startswith('```')]
            text = '\n'.join(lines)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Error parseando JSON de Claude: {e}")
            logger.error(f"Respuesta raw: {text[:500]}...")

            # Intentar extraer JSON de la respuesta
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end])
                except json.JSONDecodeError:
                    raise ValueError(f"No se pudo parsear la respuesta de Claude: {text[:200]}")
            else:
                raise ValueError(f"No se encontró JSON en la respuesta de Claude: {text[:200]}")

        # Validar campos requeridos
        required = ['title', 'content', 'excerpt', 'meta_description']
        for field in required:
            if field not in parsed:
                raise ValueError(f"Campo requerido '{field}' falta en la respuesta de Claude")

        # Truncar meta_description si excede 160 chars
        if len(parsed['meta_description']) > 160:
            parsed['meta_description'] = parsed['meta_description'][:157] + '...'

        return parsed

    def _handle_image(self, topic, selected_property):
        """
        Selecciona imagen según el tipo de tema.
        - property/family/events: foto real de la propiedad
        - otros: genera con DALL-E
        """
        image_source = topic.get('image_source', 'dalle')

        if image_source == 'property' and selected_property:
            return self._get_property_image(selected_property)
        elif image_source == 'dalle':
            return self._generate_dalle_image(topic)

        return None

    def _get_property_image(self, property_data):
        """Obtiene la imagen principal de una propiedad."""
        photo = property_data.get('main_photo_obj')
        if not photo:
            return None

        try:
            if photo.image_file:
                # Leer el archivo de imagen existente
                photo.image_file.open('rb')
                content = photo.image_file.read()
                photo.image_file.close()

                filename = f"blog_{slugify(property_data['name'])}.jpg"
                return ContentFile(content, name=filename)
        except Exception as e:
            logger.warning(f"Error obteniendo imagen de propiedad: {e}")

        return None

    def _generate_dalle_image(self, topic):
        """Genera una imagen con DALL-E 3."""
        if not self.openai_key:
            logger.warning("OPENAI_API_KEY no configurado, saltando generación de imagen DALL-E")
            return None

        try:
            import openai
            import requests

            client = openai.OpenAI(api_key=self.openai_key)

            # Crear prompt descriptivo para la imagen
            template = topic['template']
            image_prompt = (
                f"Professional travel photography style. "
                f"{template['description']} "
                f"Setting: beautiful beach houses in Lima Peru, south coast, "
                f"Punta Hermosa area. Warm lighting, inviting atmosphere. "
                f"No text or logos in the image."
            )

            logger.info(f"Generando imagen DALL-E: {image_prompt[:100]}...")

            response = client.images.generate(
                model="dall-e-3",
                prompt=image_prompt,
                size="1792x1024",
                quality="standard",
                n=1,
            )

            image_url = response.data[0].url

            # Descargar la imagen
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()

            filename = f"blog_ai_{slugify(template['key'])}.png"
            return ContentFile(img_response.content, name=filename)

        except Exception as e:
            logger.warning(f"Error generando imagen DALL-E: {e}")
            return None

    def _create_blog_post(self, parsed_content, image_file=None):
        """Crea el BlogPost como borrador."""
        from apps.blog.models import BlogPost, BlogCategory

        # Buscar o crear categoría general para posts generados
        category, _ = BlogCategory.objects.get_or_create(
            slug='ai-generated',
            defaults={
                'name': 'Generado por IA',
                'description': 'Posts generados automáticamente con IA',
                'order': 99,
            }
        )

        post = BlogPost(
            title=parsed_content['title'],
            content=parsed_content['content'],
            excerpt=parsed_content['excerpt'],
            meta_description=parsed_content['meta_description'],
            category=category,
            author='Casa Austin (IA)',
            status='draft',
        )

        if image_file:
            post.featured_image = image_file

        post.save()
        return post

    def _create_topic_plan(self, topic, keyword_data, blog_post):
        """Registra el tema generado para tracking y rotación."""
        from apps.blog.models import BlogTopicPlan

        BlogTopicPlan.objects.create(
            topic_type=topic['topic_type'],
            topic_key=topic['template']['key'],
            topic_description=topic['template']['description'],
            target_keyword=keyword_data['query'] if keyword_data else '',
            blog_post=blog_post,
        )

    def _format_dry_run(self, topic, keyword_data, selected_property, existing_posts):
        """Formatea la información del dry-run para visualización."""
        result = {
            'status': 'dry_run',
            'topic_type': topic['topic_type'],
            'topic_key': topic['template']['key'],
            'topic_description': topic['template']['description'],
            'title_hint': topic['template'].get('title_hint', ''),
            'keywords': topic['template'].get('keywords', []),
            'image_source': topic.get('image_source', 'N/A'),
            'needs_property': topic.get('needs_property', False),
        }

        if keyword_data:
            result['search_console_keyword'] = {
                'query': keyword_data['query'],
                'impressions': keyword_data.get('impressions'),
                'position': keyword_data.get('position'),
                'ctr': keyword_data.get('ctr'),
            }

        if selected_property:
            result['selected_property'] = {
                'name': selected_property['name'],
                'location': selected_property['location'],
                'capacity': selected_property['capacity_max'],
            }

        result['existing_posts_count'] = len(existing_posts)
        return result

    def _get_season_context(self):
        """Retorna contexto de temporada para Lima (hemisferio sur)."""
        month = date.today().month
        month_names = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
            5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
            9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
        }

        if month in [12, 1, 2, 3]:
            season = "Verano en Lima — temporada alta de playas. Sol, calor, playas llenas."
        elif month in [4, 5]:
            season = "Otoño en Lima — el verano termina pero aún hay días cálidos. Buenos precios."
        elif month in [6, 7, 8, 9]:
            season = "Invierno en Lima — garúa y nublado, pero las casas tienen piscina temperada."
        else:
            season = "Primavera en Lima — el clima mejora, empieza la pre-temporada de playa."

        return f"Mes actual: {month_names[month]} {date.today().year}. {season}"
