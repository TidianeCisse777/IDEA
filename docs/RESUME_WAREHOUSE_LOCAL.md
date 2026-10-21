# Résumé du déploiement local — 21 octobre 2026

## Disponible maintenant

- Warehouse PostgreSQL **16.15** + PostGIS **3.6.2** : `127.0.0.1:55432`,
  base `neolab_warehouse`.
- Interface : **http://127.0.0.1:8090**.
- DbHub **1.5.0** enregistré dans Codex sous **`neolab-warehouse`**.
- Exécution portable dans le projet, sans Docker ni service Windows.

**La base est vide.** Ni sauvegarde ni archive historique n'est disponible
sur ce PC. Les compteurs à zéro ne représentent pas la couverture NeoLab.
L'import de données réelles reste à effectuer à partir d'une source vérifiée.

## Lancer et arrêter

Depuis le terminal PowerShell à la racine du projet :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 stop
```

Les services continuent en arrière-plan après le lancement et doivent être
relancés après un redémarrage Windows. Aucun lancement au démarrage système
n'a été ajouté. Le script ne supprime ni ne réinitialise une base existante.

## Tester depuis une conversation Codex

Le MCP expose maintenant le contexte métier sans dépendre de ce fichier :
outil **`warehouse_context`** (`topic=overview`, nom de vue ou `all`),
commentaires PostgreSQL sur les 16 vues et leurs 304 colonnes scientifiques,
et vues `explore.warehouse_dictionary` et `explore.dataset_versions`.
Le [dictionnaire complet](WAREHOUSE_MCP_DICTIONARY.md) est généré depuis
le même contenu et le schéma déployé. La recette réelle confirme que les
commentaires sont retournés par `search_objects`, et les fiches par l'outil
MCP. Ce contenu est disponible à la demande, pas injecté intégralement dans
chaque message; la description de l'outil demande de lire l'overview d'abord.

L'enregistrement MCP est effectué dans la configuration personnelle Codex.
**Recharger l'extension ou redémarrer Codex et ouvrir une nouvelle conversation**
pour charger ses outils. Le processus de cette conversation ne recharge pas
automatiquement son catalogue d'outils.

Exemple de demande :

> Utilise neolab-warehouse, appelle warehouse_context avec topic=overview,
> puis avec topic=uvp_taxon_abundance. Liste les vues explore, puis exécute
> SELECT current_user, current_database(), current_setting('transaction_read_only').
> Indique si la base contient des profils UVP, sans inventer de données.

Le rôle retourné doit être `warehouse_reader` et la lecture seule `on`.
La connexion réelle MCP a été testée indépendamment de la conversation avec
`scripts/check_dbhub.cjs` : handshake, découverte des outils et requête SQL
sur `explore.uvp_projects` réussis.

## Rôles et secrets

| Rôle | Usage | Droits |
|---|---|---|
| `neolab` | Initialisation et administration locale | Propriétaire/superutilisateur local, réservé aux opérations de maintenance |
| `warehouse_navigator` | API de l'interface | SELECT sur `warehouse` et `explore`, transactions en lecture seule |
| `warehouse_reader` | DbHub / Codex | SELECT sur `explore`, accès aux tables brutes refusé, transactions en lecture seule |

Les deux comptes applicatifs n'ont ni privilège superutilisateur, création
de base ou de rôle, réplication ou contournement RLS; ni CREATE/TEMP sur la
base, ni CREATE sur le schéma public. Ils n'ont aucun droit d'écriture sur
les tables. Le délai SQL est limité à 30 s. DbHub limite les réponses à
1 000 lignes. PostgreSQL et l'interface écoutent sur la boucle locale.

Les mots de passe sont générés dans
`data/local_warehouse/credentials.json`, ignoré par Git. Ne pas copier ce
fichier dans la conversation. Aucun mot de passe n'est placé dans la
configuration Codex ou les fichiers TOML versionnés. La configuration Codex
référence seulement le lanceur PowerShell.

## Vérifications réellement exécutées

- 20 tests du contrat SQL du schéma : réussis.
- 6 tests du diagnostic warehouse et 2 tests du contrat spatial : réussis.
- 12 tests de l'interface Node : réussis.
- Test PowerShell du lanceur DbHub : réussi.
- HTTP 200 sur santé, options, couverture, carte et comparaison, y compris
  carte/couverture/comparaison avec seuil spatial nul : 8 routes vérifiées.
- Recette SQL réelle des deux comptes applicatifs : privilèges vérifiés,
  lecture brute refusée pour DbHub, et calcul géodésique PostGIS contrôlé.
- Recette MCP réelle DbHub : réussie.

Les contrôles HTTP sur une base vide ne valident pas les rapprochements sur
données réelles. La recette visuelle dans un navigateur et le scénario dans
une nouvelle conversation Codex restent à effectuer. Aucun use case
scientifique ou phase globale n'est déclaré achevé.

## Particularités Windows résolues

- Extraction PowerShell des nombreux fichiers PostgreSQL trop lente : runtime
  extrait avec Python.
- Initialisation UTF-8 sous un compte contenant un accent : utilisation des
  chemins Windows courts par le lanceur.
- Le DDL actuel contient déjà les zones FILET : la migration historique qui
  suppose un ancien ordre de colonnes n'est pas rejouée sur une base neuve.

Voir [la procédure complète](WAREHOUSE_PORTABLE.md) et
[le suivi](../ROADMAP.md) pour les commandes et limites.
