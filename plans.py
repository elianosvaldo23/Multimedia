# Definición de los planes y sus características
PLANS = {
    'basic': {
        'name': 'Plan Básico',
        'price': 'Gratis',
        'searches_per_day': 3,
        'requests_per_day': 1,
        'can_forward': False,
        'duration_days': None  # No expira
    },
    'pro': {
        'name': 'Plan Pro',
        'price': '169.99 CUP / 0.49 USD',
        'searches_per_day': 15,
        'requests_per_day': 2,
        'can_forward': False,
        'duration_days': 30,
        'features': ['15 búsquedas diarias', '2 pedidos diarios', 'No puede reenviar contenido ni guardarlo', 'Duración: 30 días']
    },
    'plus': {
        'name': 'Plan Plus',
        'price': '649.99 CUP / 1.99 USD',
        'searches_per_day': 50,
        'requests_per_day': 10,
        'can_forward': True,
        'duration_days': 30,
        'features': ['50 búsquedas diarias', '10 pedidos diarios', 'Soporte prioritario', 'Enlaces directos de descarga', 'Duración: 30 días']
    },
    'ultra': {
        'name': 'Plan Ultra',
        'price': '1049.99 CUP / 2.99 USD',
        'searches_per_day': float('inf'),  # Ilimitado
        'requests_per_day': float('inf'),  # Ilimitado
        'can_forward': True,
        'duration_days': 30,
        'features': ['Búsquedas ilimitadas', 'Pedidos ilimitados', 'Reenvío y guardado permitido', 'Enlaces directos de descarga', 'Soporte VIP', 'Duración: 30 días']
    }
}
