"""
Accès aux données « brutes » (dicts). Aujourd'hui mémoire ; demain : SQL ciblé.

get_by_id ne doit pas charger toute la liste : ici on itère une petite liste ;
avec une DB, la même fonction fera SELECT ... WHERE id = %s.
"""

_INITIAL_ROWS: list[dict] = [
    {
        "id": 1,
        "name": "steampunk",
        "type": "LXC",
        "category": "game",
        "description": "serveur minecraft sur le thème steampunk",
        "status": "off",
    },
    {
        "id": 2,
        "name": "stefano",
        "type": "VM",
        "category": "tool",
        "description": "outil de développement pour le projet stefano",
        "status": "on",
    },
]

_ROWS: list[dict] = [row.copy() for row in _INITIAL_ROWS]

def new_id(name: str) -> int:
    for row in _ROWS:
        if row["name"] == name:
            raise ValueError(f"Service with name {name} already exists")
    list_of_ids = [row["id"] for row in _ROWS]
    return max(list_of_ids) + 1

def fetch_all_rows() -> list[dict]:
    """Liste complète (pour listing tolérant)."""
    return list(_ROWS)


def reset_rows() -> None:
    """Utile pour isoler les tests automatisés."""
    _ROWS.clear()
    _ROWS.extend(row.copy() for row in _INITIAL_ROWS)


def fetch_row_by_id(service_id: int) -> dict | None:
    """Une ligne par id (pas de chargement de toute la table en SQL réel)."""
    for row in _ROWS:
        if row["id"] == service_id:
            return row
    return None


def fetch_row_by_name(service_name: str) -> dict | None:
    """Une ligne par nom (utile pour vérifier l'unicité métier)."""
    for row in _ROWS:
        if row["name"] == service_name:
            return row
    return None

def add_service(service: dict) -> dict:
    """
    Simule un INSERT SQL:
    - l'id est généré côté persistance,
    - le status par défaut est initialisé ici.
    """
    new_row = {**service}
    new_row["id"] = new_id(new_row["name"])
    new_row.setdefault("status", "off")
    _ROWS.append(new_row)
    return new_row