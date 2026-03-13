En tant qu’**admin infra**, je veux :
- **voir l’état de santé global** de l’orchestrateur afin de **savoir rapidement si toute les fonctionnalités sont disponibles**.
- **voir l’état de santé de chaque service/node/cluster** afin de **savoir rapidement si un service/node/cluster est en erreur**.
- **ajouter un nouveau service/node/cluster** afin de **pouvoir gérer les ressources de l’orchestrateur**.
- **supprimer un service/node/cluster** afin de **pouvoir gérer les ressources de l’orchestrateur**.
- **modifier un service/node/cluster** afin de **pouvoir gérer les ressources de l’orchestrateur**.
- **voir les logs de l’orchestrateur** afin de **pouvoir diagnostiquer les erreurs**.
- **lors de l'ajout d'un nouveau service/node/cluster, le selectionner dans liste des service/node/cluster détectés par le NodeConductor ou l'ajouter manuellement** afin de **pouvoir gérer les ressources de l’orchestrateur**.
- **je souhaiterai que la partie "opérateur" soit utilisable pour un agent déployé sur un node pour gérer les ressources** afin de **pouvoir intégrer le NodeConductor dans mon "home lab"**.
- **gérer les utilisateurs autorisés à utiliser le NodeConductor sur le discord ou l'interface web**.
- **avoir un mode simulation pour l'admin, l'opérateur et l'utilisateur** afin de **présentation et de test**.

En tant qu’**opérateur**, je veux :
- **démarrer/arrêter un service/node/cluster** afin de **pouvoir gérer les ressources de l’orchestrateur**.
- **signaler un problème** afin de **pouvoir informer les admins infra**.
- **voir l'état de santé global** afin de **savoir rapidement si toute les fonctionnalités sont disponibles**.
- **ajouter/supprimer/modifier un nouvelle utilisateur Discord/web autorisé** afin de **pouvoir utiliser le NodeConductor sur le discord/web**.
- **voir la liste des utilisateurs autorisés à utiliser le NodeConductor sur le discord/web**.

En tant qu’**utilisateur Discord autorisé**, je veux :
- **taper une commande @NodeConductor help** afin de **obtenir la liste des commandes disponibles**.
- **taper une commande @NodeConductor status** afin de **connaître l’état d’un service/node/cluster**.
- **taper une commande @NodeConductor start/stop/restart** afin de **démarrer/arrêter/redémarrer un service/node/cluster**.
- **taper une commande @NodeConductor health** afin de **connaître l’état de santé global simplifié**.
- **signaler un problème** afin de **pouvoir informer les admins infra**.

En tant qu’**utilisateur web autorisé**, je veux :
- **les mêmes droits qu'un utilisateur Discord autorisé** afin de **pouvoir utiliser le NodeConductor sur le web**.

En tant qu’**agent de sécurité**, je veux :
- **que la connexion à l'interface web soit sécurisée** afin de **protéger les données des utilisateurs et de l'infrastructure**.
- **que les données sensibles soient stockées de manière sécurisée et chiffrées** afin de **protéger les données des utilisateurs et de l'infrastructure**.
- **que la connection admin soit locale (sur le même LAN)** afin de **protéger les données des utilisateurs et de l'infrastructure**.
- **que la connection agent soit sécurisée** afin de **protéger les données des utilisateurs et de l'infrastructure**.
