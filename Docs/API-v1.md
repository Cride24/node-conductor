# 1. API v1 : Définition précise de chaque endpoint:

## 1.1. GET /api/v1/health

	- **But** : connaître l’état global simplifié de l’orchestrateur.
	- **Méthode** : `GET`
	- **URL** : `/api/v1/health`
	- **Entrée** : rien (pour l’instant pas d’auth).
	- **Réponse 200 (OK)** : un JSON du type :

		```json
		{
		"status": "OK",
		"version": "0.1.0",
		}
		```

## 1.2. GET /api/v1/services

	- **But** : lister les services connus par l’orchestrateur.
	- **Méthode** : `GET`
	- **URL** : `/api/v1/services`
	- **Entrée** : rien.
	- **Réponse 200 (OK)** :

		```json
		[
		{
			"id": "steampunk",
			"name": "Steampunk service"
		}
		{
			"id": "1234",
			"name": "1234 service"
		}
		]
		```

## 1.3. GET /api/v1/services/{service_id}

	- **But** : obtenir le détail d’un service.
	- **Méthode** : `GET`
	- **URL** : `/api/v1/services/{service_id}`
	- **Entrée** :
	- `service_id` dans l’URL (ex. `steampunk`).
	- **Réponse** 
		- **200 (OK)** :

			```json
			{
				"id": "steampunk",
				"name": "Steampunk service",
				"description": "Server Minecraft Steampunk"
				"status": "ON"
			}
			```
	
		- **404 (Not Found)** si le service n’existe pas :

			```json
			{
			"error": "SERVICE_NOT_FOUND",
			"message": "Service 'xyz' not found"
			}
			```

## 1.4. POST /api/v1/services/{service_id}/start|stop

	- **But** : demander le démarrage ou l'arrêt d'un service.
	- **Méthode** : `POST`
	- **URL** : `/api/v1/services/{service_id}/start` ou `/api/v1/services/{service_id}/stop` (selon le cas).
	- **Entrée** :
		- `service_id` dans l’URL.
	- **Réponses** :
		- **200 (OK)** si la demande est acceptée :

			```json
			{
			"service_id": "steampunk",
			"requested_state": "ON" ou "OFF",
			"job_id": "job-1234"
			}
			```

		- **400 / 409** si l’état actuel ne permet pas l’action (ex. déjà en `STARTING`).

			```json	
			{
			"error": "INVALID_STATE_TRANSITION",
			"message": "Service 'steampunk' is already in state 'STARTING'" or "Service 'steampunk' is already in state 'STOPPING'"
			"job_id": "job-1234"
			}
			```

		- **404** si le service n’existe pas.

			```json
			{
			"error": "SERVICE_NOT_FOUND",
			"message": "Service 'xyz' not found"
			}
			```
