# MCP EcoTaxa — Ce que l'agent peut faire

Ce document résume, en langage utilisateur, ce que le MCP EcoTaxa apporte à l'agent IDEA. Le principe central est simple : **explorer avant d'exporter**.

Le MCP sert à savoir quels projets EcoTaxa sont accessibles, où et quand ils ont des données, quels taxons y sont attestés, quels champs sont disponibles, et si plusieurs projets peuvent être combinés. Il est en lecture seule : il ne modifie pas EcoTaxa et ne télécharge pas les exports complets.

---

## 1. Explorer ce à quoi le compte a accès

Le MCP peut lister les projets visibles par les identifiants EcoTaxa configurés dans l'environnement.

Questions typiques :

- « Quels projets EcoTaxa sont accessibles avec le compte configuré ? »
- « Quels projets UVP6 sont accessibles ? »
- « Cherche les projets EcoTaxa liés à Amundsen. »
- « Présente rapidement le projet 42. »

Tools utilisés :

| Besoin | Tool IDEA | Tool MCP |
|---|---|---|
| Lister les projets accessibles | `list_ecotaxa_projects` | legacy IDEA |
| Chercher par titre ou instrument | `find_ecotaxa_projects` | `search_projects` |
| Voir une fiche projet | `preview_ecotaxa_project` | `get_project` |

Point important : la liste dépend du compte EcoTaxa utilisé. Le MCP ne voit pas tout EcoTaxa, seulement les projets autorisés pour ce compte.

---

## 2. Filtrer les projets par zone et période

EcoTaxa ne fournit pas directement une recherche multi-projets par région. Le MCP le permet grâce au cache local `samples_cache`, qui indexe les samples par projet, latitude, longitude, date et instrument.

Questions typiques :

- « Quels projets EcoTaxa couvrent la baie de Baffin en 2024 ? »
- « Quels projets ont des samples au-dessus de 75°N entre 2015 et 2024 ? »
- « Quels projets accessibles couvrent la baie de Baffin entre 2015 et 2024 ? »

Chemin attendu :

```text
zone nommée
→ get_zone_filter
→ find_ecotaxa_projects_in_region
```

Exemple validé :

```text
Quels projets EcoTaxa accessibles couvrent la baie de Baffin entre 2015 et 2024,
et parmi eux lesquels attestent Calanus glacialis validé ?
```

Tool calls validés dans LangSmith :

```text
get_zone_filter("baie de Baffin")
→ find_ecotaxa_projects_in_region(bbox=baie_de_Baffin, date_range=2015-2024)
→ find_ecotaxa_observations(taxon="Calanus glacialis", bbox=baie_de_Baffin, date_range=2015-2024, status="V")
```

---

## 3. Trouver où un taxon est attesté

Le MCP peut chercher les samples dont le projet atteste un taxon donné, avec ou sans filtre spatial/temporel.

Questions typiques :

- « Où trouve-t-on Calanus glacialis dans mes projets EcoTaxa accessibles ? »
- « Où Calanus glacialis est-il validé en baie de Baffin entre 2015 et 2024 ? »
- « Est-ce que Calanus finmarchicus est présent dans le projet 42 ? »
- « Combien de Calanus finmarchicus validés dans le projet 42 ? »

Tools utilisés :

| Besoin | Tool IDEA | Tool MCP |
|---|---|---|
| Où un taxon est observé | `find_ecotaxa_observations` | `find_observations` |
| Compter V/P/D par projet | `count_ecotaxa_taxa` | `taxa_stats` |
| Chercher un nom taxonomique | via résolution interne | `search_taxa` |

Limite V1 : `find_ecotaxa_observations` travaille à granularité projet-filtrée. Il dit que les samples appartiennent à un projet où le taxon est attesté. Pour des counts précis par projet, il faut enchaîner avec `count_ecotaxa_taxa`.

---

## 4. Inspecter un projet avant export

Avant de télécharger un gros export EcoTaxa, le MCP peut vérifier si le projet contient les champs nécessaires.

Questions typiques :

- « Avant d'exporter le projet 14622, vérifie s'il contient latitude, longitude, date, profondeur et taxon validé. »
- « Quelles colonnes a le projet 42 ? »
- « Y a-t-il une colonne profondeur ? »
- « Est-ce qu'il y a des champs morphométriques utiles ? »

Tools utilisés :

| Besoin | Tool IDEA | Tool MCP |
|---|---|---|
| Voir le schéma d'un projet | `inspect_ecotaxa_project_schema` | `get_project_schema` |
| Voir les codes internes de free fields | `inspect_ecotaxa_project_schema(verbose=True)` | `get_project_schema(verbose=True)` |

Le schéma est organisé par niveaux :

- `sample` : déploiement, station, date, lat/lon, free fields sample
- `acquisition` : acquisition instrument
- `object` : objet/image, classification, morphométrie, profondeur si disponible

---

## 5. Inspecter la distribution d'une colonne

Le MCP peut regarder une colonne précise sans exporter tout le projet.

Questions typiques :

- « Quelle est la plage de profondeur du projet 42 ? »
- « Quelles sont les valeurs de classif_qual ? »
- « Inspecte la colonne orig_id dans le projet 42. »
- « Quelle est la distribution de area ? »

Tool utilisé :

| Besoin | Tool IDEA | Tool MCP |
|---|---|---|
| Distribution d'une colonne | `inspect_ecotaxa_column` | `get_column_distribution` |

Résultats possibles :

- numérique : min, max, moyenne, médiane, quartiles, n
- texte : valeurs fréquentes, counts, distincts
- ambigu : erreur `AMBIGUOUS_COLUMN` avec candidats par niveau

Exemple de bonne récupération :

```text
inspect_ecotaxa_column(project_id=42, column_name="depth_min")
```

---

## 6. Comparer plusieurs projets avant fusion

Le MCP peut comparer les schémas de plusieurs projets avant un export combiné.

Questions typiques :

- « Compare les projets 14844, 14853, 14859 et 17498 avant export combiné. »
- « Quelles colonnes sont communes entre ces projets ? »
- « Y a-t-il des conflits bloquants de type ? »

Tool utilisé :

| Besoin | Tool IDEA | Tool MCP |
|---|---|---|
| Comparer les schémas | `compare_ecotaxa_projects` | `compare_project_schemas` |

Le retour indique :

- colonnes communes
- colonnes uniques à chaque projet
- conflits de type
- conflits de niveau
- sévérité des conflits (`warning` ou `blocker`)

---

## 7. Naviguer dans le catalogue

Le MCP expose aussi une navigation détaillée projet → sample → acquisition → objet.

Questions typiques :

- « Liste les samples du projet 42. »
- « Donne les métadonnées complètes du sample EcoTaxa 42000002. »
- « Liste les acquisitions du projet 42. »
- « Liste quelques objets d'un sample. »
- « Donne le contexte complet de cet objet. »

Tools MCP :

| Niveau | Tool MCP |
|---|---|
| Projet | `get_project`, `search_projects` |
| Samples | `list_project_samples`, `get_sample` |
| Acquisitions | `list_project_acquisitions`, `get_acquisition` |
| Objets | `list_sample_objects`, `get_object` |

Côté agent IDEA, certains wrappers sont disponibles directement, par exemple `get_ecotaxa_sample` pour les métadonnées complètes d'un sample.

---

## 8. Ce que le MCP ne fait pas

Le MCP EcoTaxa V1 est volontairement limité.

Il ne fait pas :

- d'export complet TSV/CSV ;
- de téléchargement d'images ou de vault EcoTaxa ;
- d'annotation ou modification de projet ;
- de classification ;
- de calcul d'abondance ou biomasse final ;
- de support EcoPart V1 ;
- de filtrage par utilisateur final distinct du compte service.

Pour exporter réellement des objets, IDEA utilise encore le tool natif :

```text
query_ecotaxa(project_id=..., taxon=..., status="V")
```

Règle de routage : `query_ecotaxa` doit être réservé aux demandes explicites du type « charge », « exporte », « télécharge », « récupère les données ». Les questions d'exploration doivent rester sur les tools MCP.

---

## 9. Cache et fraîcheur des données

Le cache local `data/ecotaxa_cache.sqlite` permet les recherches géographiques et temporelles rapides.

Il contient notamment :

- `samples_cache` : samples agrégés par projet, lat/lon moyenne, date min/max, instrument, nombre d'objets
- `project_schemas_cache` : snapshot de schéma projet
- `sync_runs` : historique des synchronisations

Remplissage :

- sync nightly à 3 AM UTC via APScheduler dans le container MCP
- resync manuel via `POST /admin/resync`
- scripts/tests Python ad hoc

Le cache reflète les droits du compte EcoTaxa configuré. Si les credentials changent, il faut resynchroniser et éviter de mélanger des caches issus de comptes différents.

---

## 10. Exemples de bonnes questions de démonstration

Ces questions montrent bien la valeur du MCP.

```text
Quels projets EcoTaxa accessibles couvrent la baie de Baffin entre 2015 et 2024,
et parmi eux lesquels attestent Calanus glacialis validé ?
Donne les périodes couvertes, le nombre de samples par projet,
puis recommande quel projet inspecter avant export. N'exporte rien.
```

```text
Avant d'exporter le projet 14622, vérifie s'il contient latitude, longitude,
date, profondeur et taxon validé.
```

```text
Compare les projets 14844, 14853, 14859 et 17498 avant un export combiné.
Dis-moi les colonnes communes et les conflits bloquants s'il y en a.
```

```text
Où trouve-t-on Calanus glacialis dans mes projets EcoTaxa accessibles ?
```

```text
Combien de Calanus finmarchicus validés dans le projet 42 ?
```

---

## 11. Résumé exécutif

Le MCP EcoTaxa transforme EcoTaxa en catalogue exploratoire interrogeable par l'agent :

- **quoi** : projets, samples, acquisitions, objets, taxons, colonnes
- **où** : recherche par zone géographique
- **quand** : recherche par période
- **quel taxon** : observations et counts V/P/D
- **quel schéma** : champs disponibles avant export
- **compatible ou non** : comparaison multi-projets

Sa meilleure utilité est de répondre à la question :

> « Est-ce que ces données existent, où, quand, dans quels projets, avec quels champs, et est-ce que ça vaut la peine d'exporter ? »

