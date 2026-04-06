services = [
    {
        "id": 1,
        "name": "steampunk",
        "type": "game",
        "description": "serveur minecraft sur le thème steampunk",
        "status": "off"
    },
    {
        "id": 2,
        "name": "stefano",
        "type": "tool",
        "description": "outil de développement pour le projet stefano",
        "status": "on"
    }
]

def list_services():
    return services

def get_service_by_id(service_id):
    for service in services:
        if service["id"] == service_id:
            return service
    return None
