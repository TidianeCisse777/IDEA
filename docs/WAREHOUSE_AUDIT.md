# Audit et débogage des agents

Deux journaux distincts, qui ne répondent pas à la même question :

| | **Audit** (serveur) | **Trace de débogage** (poste) |
|---|---|---|
| Question | qui a lu quoi, quand, avec quel agent | pourquoi l'agent a répondu ça |
| Où | journal de PostgreSQL, sur le serveur | fichier privé sur le poste de la personne |
| Qui l'active | l'administrateur, pour tous les comptes | la personne, quand elle en a besoin |
| Désactivable par l'utilisateur | **non** | oui (`trace off`) |
| Contenu | chaque requête SQL, compte, heure, agent, refus d'accès | chaque appel d'outil : SQL, durée, lignes, erreur, extrait du résultat |
| Outil | `scripts/warehouse_audit.py` | `scripts/warehouse_connect.py trace show` |

Aucun des deux ne contient de mot de passe.

## Pour qui ça fonctionne

| | Audit (serveur) | Nom de l'agent dans l'audit, trace locale |
|---|---|---|
| Comptes personnels, restreints ou « toutes les données » | **oui, tous**, quel que soit l'agent ou le poste | oui, si le poste a la version à jour du dépôt (`git pull`) |
| `warehouse_reader` (version portable Windows) | oui | non (lanceur DbHub historique) |
| Navigateur web, chargeurs, compte propriétaire | non (volontaire) | — |
| Connexion directe (psql, script, notebook) avec un compte personnel | oui (outil : le nom que déclare le client, `psql` par exemple, sinon `?`) | — |

L'audit est appliqué par le serveur : il ne dépend ni de l'agent, ni de la version des scripts sur le poste de la
personne. Il suffit que l'administrateur l'ait activé (voir [Ce qu'il faut côté serveur](#ce-quil-faut-côté-serveur)).
Seuls l'étiquette de l'agent et la trace de débogage viennent du lanceur `warehouse_connect.py run` : une personne
qui n'a pas mis à jour sa copie du dépôt reste auditée, mais apparaît avec l'outil `?` et n'a pas `trace`.

## Audit des requêtes (administrateur)

### Ce qui est journalisé

- **Toutes les requêtes** des comptes personnels (restreints ou « toutes les données ») et du rôle partagé
  `warehouse_reader` : texte SQL, paramètres, compte, heure, session.
- **L'agent utilisé** : chaque connexion par MCP est étiquetée `neolab-mcp:<agent>` (par exemple
  `neolab-mcp:claude-code`, `neolab-mcp:codex-mcp-client`). La recette `check` apparaît comme `neolab-check`.
  Une connexion directe apparaît avec le nom que déclare l'outil (`psql`, par exemple), ou `?` s'il n'en déclare pas.
- **Les refus et échecs** : une tentative de lire une table brute (`permission denied for schema warehouse`) ou
  d'écrire est visible avec `--errors`.

Ne sont **pas** journalisés : les lignes renvoyées (seulement la requête), le navigateur web (application aux
requêtes fixes, à fort volume) et les chargeurs ou le compte propriétaire.

**Un compte ne peut pas couper son propre audit.** Le réglage `log_statement` est réservé au superuser : `SET
log_statement = 'none'` est refusé, et `ALTER ROLE` l'est aussi, puisque la session est en lecture seule.
Vérifié par `tests/test_warehouse_roles_fair.py`.

### Relire

```bash
# Avec les variables WAREHOUSE_POSTGRES_* du compte propriétaire
python scripts/warehouse_audit.py                              # 50 dernières requêtes
python scripts/warehouse_audit.py --summary                    # une ligne par compte : requêtes, erreurs, sessions, agents
python scripts/warehouse_audit.py --user ines --since 2026-10-01
python scripts/warehouse_audit.py --errors                     # refus et échecs seulement
python scripts/warehouse_audit.py --csv > audit.csv            # export complet
python scripts/warehouse_audit.py --file postgresql-2026-10-31.csv   # fichiers copiés, sans connexion
```

Exemple réel (base de test, 31 octobre 2026) :

```
compte               requêtes erreurs sessions  première                dernière                outils
jtest_audit                19       1        4  2026-10-31 15:45:24.538 2026-10-31 15:47:52.545 neolab-mcp:claude-code, …

2026-10-31 15:45:44  jtest_audit  ?                         ERREUR permission denied for schema warehouse | select * from warehouse.uvp_profile limit 5
2026-10-31 15:47:52  jtest_audit  neolab-mcp:claude-code    select * from explore.my_access LIMIT 1001
```

Les `BEGIN READ ONLY` / `COMMIT` que DbHub ajoute autour de chaque requête sont masqués (`--all` pour les voir).
Le `LIMIT 1001` final est ajouté par DbHub : c'est ce qui a réellement été exécuté.

### Ce qu'il faut côté serveur

1. **Le serveur écrit son journal en fichiers CSV.** C'est déjà configuré dans `docker-compose.warehouse.yml` :
   `logging_collector=on`, `log_destination=csvlog`, un fichier par jour dans le dossier `log/` du volume de
   données. Sur un autre hébergement, demander ces mêmes réglages dans `postgresql.conf`.
2. **Un superuser active l'audit par compte.** Le déploiement l'applique à tous les comptes existants, et
   `warehouse_user.py create` aux nouveaux, en affichant `Audit des requêtes: actif`. Avec un propriétaire non
   superuser (hébergement géré), il affiche `NON actif` sans faire échouer quoi que ce soit : un superuser doit
   alors lancer le déploiement une fois, ou accorder `GRANT SET ON PARAMETER log_statement` au propriétaire.
3. **Lire le journal** demande un superuser, ou les rôles `pg_monitor` et `pg_read_server_files`. Sinon, copier
   les fichiers `*.csv` du dossier `log/` et utiliser `--file`.

Pour activer l'audit sur un warehouse Docker déjà en service :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d neolab-warehouse-db  # recrée le conteneur, garde les données
python scripts/deploy_warehouse_postgres.py           # applique l'audit aux comptes existants
python scripts/warehouse_audit.py --summary           # vérifier
```

Avec `logging_collector`, les messages du serveur ne passent plus par `docker logs` mais par ces fichiers. Les
erreurs des scripts d'initialisation restent visibles dans `docker logs`.

### Conservation et confidentialité — à décider par le labo

- Les fichiers ne sont **jamais supprimés automatiquement** : un par jour, dans le volume de données, inclus dans
  les sauvegardes. Fixer une durée (par exemple 12 mois) et supprimer les plus anciens
  (`docker exec neolab-warehouse-db find /var/lib/postgresql/data/log -name '*.csv' -mtime +365 -delete`).
- Les requêtes des chercheurs deviennent lisibles par l'administrateur, y compris les valeurs écrites dans leurs
  filtres (`WHERE taxon = '…'`). Le dire aux personnes à la création du compte, et décider qui peut lire l'audit.

## Trace de débogage (chaque personne, sur son poste)

Pour comprendre ce qu'un agent a fait : quelles requêtes, dans quel ordre, avec quel résultat.

```bash
python scripts/warehouse_connect.py trace on       # puis redémarrer l'agent
# … poser ses questions à l'agent …
python scripts/warehouse_connect.py trace show     # 20 derniers appels (--last N, --full pour le SQL complet)
python scripts/warehouse_connect.py trace off      # arrêter (le fichier est conservé)
python scripts/warehouse_connect.py trace clear    # effacer le fichier
```

Exemple réel :

```
2026-10-31T15:47:48  claude-code  tools/list             11 ms  ok
2026-10-31T15:47:52  claude-code  execute_sql            22 ms  ok, 1 ligne(s)
    select * from explore.my_access
```

Chaque appel enregistre l'agent, l'outil, ses arguments (le SQL), la durée, le statut, le nombre de lignes, une
éventuelle troncature (au-delà de 1000 lignes) ou erreur, et les 300 premiers caractères du résultat. Le fichier
est à côté des identifiants (`~/.config/neolab-warehouse/trace.jsonl`, droits `600`), ne contient aucun mot de
passe, et ne quitte pas le poste. L'extrait du résultat contient des données que la personne a de toute façon le
droit de voir : désactiver la trace quand elle n'est plus utile.

Le même lanceur (`warehouse_connect.py run`) sert à tous les agents : la trace et l'étiquette d'agent de l'audit
fonctionnent pour Claude Code, Codex, Gemini, OpenCode et tout autre client MCP.

## État de validation (31 octobre 2026)

- Docker, compte restreint, vrai Claude Code : 19 requêtes et une tentative de lecture d'une table brute
  retrouvées dans l'audit, avec le compte et l'agent (`neolab-mcp:claude-code`); trace locale correspondante.
- Codex 0.166 et Gemini CLI 0.66 fonctionnent à travers le même lanceur (connexion établie, agent identifié dans
  la trace).
- Le compte ne peut pas désactiver son audit (`SET`, `ALTER ROLE` refusés); test automatique ajouté.
- 105 tests verts en direct, dont le cas propriétaire non superuser (audit signalé non actif, déploiement intact).
- Trouvé en route : la version récente du protocole MCP (2026-07-28, Claude Code 2.1) n'ouvre plus par
  `initialize`; le nom de l'agent est lu à ses deux emplacements. DbHub ignore `application_name` dans la chaîne
  de connexion : l'étiquette passe par la variable `PGAPPNAME`.
- Non testé : hébergement géré réel (lecture du journal sans superuser), Windows.
