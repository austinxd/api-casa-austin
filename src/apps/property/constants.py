"""
Constantes para el sistema de casas y reproductores de música
"""

HOUSE_CHOICES = [
    ('casa-austin', 'Casa Austin'),
    ('casa-verde', 'Casa Verde'),
    ('casa-amarilla', 'Casa Amarilla'),
    ('casa-azul', 'Casa Azul'),
]

HOUSE_NAME_TO_ID = {
    'casa-austin': 1,
    'casa-verde': 2,
    'casa-amarilla': 3,
    'casa-azul': 4,
}

NUMBER_TO_HOUSE_NAME = {
    '1': 'casa-austin',
    '2': 'casa-verde',
    '3': 'casa-amarilla',
    '4': 'casa-azul',
}


def get_house_id(house_name):
    """
    Convierte el nombre de casa (slug) a house_id numérico para la API de música.
    
    Args:
        house_name: Slug de la casa (ej: 'casa-austin')
        
    Returns:
        int: ID numérico de la casa (1-4)
        
    Raises:
        ValueError: Si el nombre de casa no es válido
    """
    if not house_name:
        raise ValueError("El nombre de casa no puede estar vacío")
    
    house_id = HOUSE_NAME_TO_ID.get(house_name)
    if house_id is None:
        raise ValueError(f"Nombre de casa inválido: {house_name}. Valores válidos: {list(HOUSE_NAME_TO_ID.keys())}")
    
    return house_id
