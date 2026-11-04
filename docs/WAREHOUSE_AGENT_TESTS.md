# Tester un agent sur le warehouse (batterie de questions)

`scripts/agent_battery.py` pose une série de questions de chercheur à Claude Code branché au warehouse par
MCP (DbHub), comme le ferait un utilisateur, puis note ses réponses. À relancer après chaque changement de la
base, des vues ou des consignes données aux agents (`scripts/warehouse_context.py`).

```bash
python scripts/agent_battery.py                          # tous les cas, 5 agents à la fois
python scripts/agent_battery.py --only baffin_samples    # un seul cas
```

Prérequis : le warehouse déployé et chargé, Claude Code connecté (`claude`), DbHub installé
(`python scripts/warehouse_connect.py install-dbhub`), et le compte propriétaire dans l'environnement ou
`.env.warehouse` (il sert seulement à calculer les bonnes réponses et à créer le compte de l'agent).

## Comment ça marche

- Les cas sont dans `tests/agent_battery/*.json` : une question, la requête SQL qui calcule la bonne réponse
  (`expect_sql`), et au besoin des motifs qui doivent apparaître (`must_mention`), des valeurs qui ne doivent
  pas apparaître (`must_not_sql`, par exemple la somme de projets en double) et une tolérance.
- Les bonnes réponses sont recalculées dans la base à chaque lancement : elles suivent les données.
- L'agent reçoit un compte personnel temporaire, en lecture seule, supprimé à la fin; aucun mot de passe de
  la base n'est dans son environnement. Chaque question est posée dans un dossier vide.
- Une réponse réussit si chaque nombre attendu y figure (entier exact, décimal à la tolérance près), si chaque
  motif obligatoire est présent et si aucune valeur interdite n'apparaît.
- Rapport : `data/agent_battery/<date>/report.md` (tableau) et `report.json` (réponses complètes); le flux de
  chaque agent est dans `<cas>.jsonl`.

La notation lit des nombres : elle vérifie les chiffres et les pièges écrits dans les cas, pas toute la
qualité d'une réponse. Relire les réponses d'un cas qui échoue, et ajouter un cas pour chaque erreur trouvée.

## Coût

Chaque question est une session d'agent : environ 0,10 à 0,25 $ au tarif de l'API (10 cas : 1,4 à 1,7 $
observés le 4 novembre 2026).

## Ajouter un cas

Ajouter un objet à `tests/agent_battery/ecotaxa_cases.json` (ou un nouveau fichier passé avec `--cases`),
écrire la question comme un chercheur la poserait, sans indiquer les tables à utiliser, et noter le piège
visé dans `trap`.
