# Personas por tipo de cama para calcular capacidad de dormitorios
BED_CAPACITY = {'matrimonial': 2, 'queen': 2, 'king': 2, 'individual': 1}


def calc_bed_capacity(detalle_dormitorios):
    """Calcula capacidad total de camas y resumen desde detalle_dormitorios.

    Returns:
        (total_personas, resumen_str)
        Ej: (14, "2 matrimonial, 2 queen, 6 individual")
    """
    if not detalle_dormitorios or not isinstance(detalle_dormitorios, dict):
        return 0, ''
    totals = {}
    for room in detalle_dormitorios.values():
        if not isinstance(room, dict):
            continue
        for tipo, cant in room.get('camas', {}).items():
            if cant and cant > 0:
                totals[tipo] = totals.get(tipo, 0) + cant
    personas = sum(cant * BED_CAPACITY.get(t, 1) for t, cant in totals.items())
    resumen = ', '.join(f"{cant} {tipo}" for tipo, cant in totals.items())
    return personas, resumen
