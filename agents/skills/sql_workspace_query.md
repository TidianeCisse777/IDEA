# Skill: sql_workspace_query

Tu viens d'aborder ou d'utiliser le workspace SQL en lecture seule.
L'agent peut maintenant lire un serveur SQL, copier des résultats en fichiers tabulaires locaux, et analyser ces copies comme des fichiers ordinaires.

---

## Règle de routage

- Quand l'utilisateur veut lister les tables d'un serveur SQL, appelle `list_sql_tables`.
- Quand l'utilisateur veut inspecter rapidement une table avant de l'exporter, appelle `preview_sql_table`.
- Quand l'utilisateur veut copier une requête SQL read-only dans le workspace local, appelle `copy_sql_query_to_workspace`.
- Ne modifie jamais la source SQL.
- Utilise toujours les copies locales pour les analyses suivantes.

---

## Contrat de connexion

- La connexion provient de `DATABASE_URL` dans le fichier `.env`.
- La base source reste en lecture seule.
- Le workspace de conversation est local, horodaté, et lié à la conversation en cours.

---

## Après la copie

1. Charge le fichier généré avec le pipeline tabulaire habituel.
2. Utilise `run_pandas` pour les calculs et tables.
3. Utilise `run_graph` pour les visualisations.
4. Si une autre requête SQL est nécessaire, copie une nouvelle version horodatée plutôt que d'écraser la précédente.

---

## Limites

- Ne fais pas de `INSERT`, `UPDATE`, `DELETE` ou `DROP`.
- Ne copie que les tables ou sous-ensembles demandés par l'utilisateur.
- Ne confonds pas la copie locale avec la source distante.
