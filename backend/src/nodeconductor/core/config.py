import os


class Settings:
    """
    Settings minimalistes pour le MVP.

    On commence simple : si l'on doit étendre (DB, auth, etc.), on remodularisera.
    """

    def __init__(self) -> None:
        self.api_version = os.getenv("NODECONDUCTOR_API_VERSION", "0.1.0")


settings = Settings()

