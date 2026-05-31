# Regles de code

Ce document pose des regles simples pour garder NodeConductor lisible pendant que le projet grandit.

Elles sont inspirees de l'esprit de l'ecole 42 : petites fonctions, responsabilites claires, fichiers faciles a parcourir. Ce sont des guides souples, pas une police automatique.

---

## 1. Objectif

Le code doit rester :

- lisible apres une pause ;
- facile a tester ;
- facile a expliquer ;
- decoupe par responsabilite ;
- accueillant pour l'apprentissage.

Une solution un peu plus longue mais claire est preferee a une solution compacte et obscure.

---

## 2. Taille des fonctions

Objectif indicatif :

```text
viser environ 25 lignes par fonction
```

Si une fonction depasse franchement cette taille, se demander si elle melange :

- validation ;
- acces DB ;
- orchestration ;
- mapping de donnees ;
- gestion d'erreur ;
- reponse HTTP.

Une fonction peut depasser cette limite si le decoupage rendrait le code moins clair.

---

## 3. Taille des fichiers

Objectif indicatif :

```text
viser environ 200 lignes par fichier
```

Quand un fichier grossit, chercher un decoupage par domaine :

- route API ;
- schema Pydantic ;
- service metier ;
- repository ;
- worker ;
- tests du flux concerne.

Un fichier peut depasser cette limite temporairement si la structure du projet n'est pas encore stabilisee.

---

## 4. Responsabilite par couche

Regle generale :

```text
API -> services metier -> repositories -> base de donnees
```

La route API doit :

- recevoir la requete ;
- convertir les erreurs metier en codes HTTP ;
- renvoyer un schema API.

Le service metier doit :

- appliquer les regles de domaine ;
- coordonner plusieurs repositories si besoin ;
- rester testable sans details HTTP.

Le repository doit :

- parler a PostgreSQL ;
- renvoyer des donnees brutes ;
- eviter de porter le contrat public de l'API.

Le worker doit :

- executer des jobs deja acceptes ;
- posseder les changements operationnels de `services.status` ;
- rester separe de la validation HTTP.

---

## 5. Commentaires

Un bon commentaire explique une intention ou une regle.

Exemples utiles :

- "status est absent ici par conception" ;
- "202 signifie qu'un nouveau job est cree" ;
- "le worker possede cette transition" ;
- "voir Docs/Jobs-et-actions.md".

Commentaires a eviter :

- commenter le nom d'une fonction ;
- repeter une ligne evidente ;
- ecrire une documentation complete dans le code.

Les details longs vont dans `Docs/`.

---

## 6. Tests

Les tests doivent nommer le comportement metier.

Exemples :

- idempotence d'une demande start ;
- conflit entre start et stop ;
- annulation d'un job pending ;
- echec worker qui met le service en error.

Les tests peuvent contenir de courts commentaires quand ils racontent une regle importante.

---

## 7. Exceptions

Ces regles sont des aides a la decision.

On peut les depasser si :

- la lisibilite s'ameliore ;
- le decoupage ajouterait trop d'indirection ;
- le code est temporaire et clairement identifie ;
- une refonte plus large est prevue dans une etape suivante.

L'important est de garder une intention claire et documentee.
