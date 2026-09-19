# QA du chargement EcoTaxa

Contrôle exécuté le 2026-09-18 sur PostgreSQL local `postgres` après le chargement des projets accessibles par l'API EcoTaxa.

## Couverture source

- Projets EcoTaxa accessibles : **23**
- Samples retournés par EcoTaxa : **6 138**
- Projets présents dans `warehouse.ecotaxa_project` : **23**
- Samples présents dans `warehouse.ecotaxa_sample` : **6 138**
- Comparaison API ↔ warehouse : **aucun écart** par projet

## Intégrité relationnelle

- Doublons `(dataset_version_id, project_id, sample_id)` : **0**
- Samples sans projet parent : **0**
- Projets sans `dataset_version` parent : **0**
- Samples sans `dataset_version` parent : **0**
- Coordonnées hors plages latitude/longitude : **0**
- `sample_orig_id` manquant : **0**

## Zones maritimes

Affectation calculée avec `shared_data/geo/zones_registry.geojson` et conservée avec son statut :

| Statut | Nombre |
|---|---:|
| assigned | 2 127 |
| outside | 1 770 |
| ambiguous | 47 |
| unresolved | 2 194 |

Les **2 194** samples `unresolved` appartiennent principalement au projet 2331 (2 193 samples) et n'ont pas de coordonnées dans l'API EcoTaxa. Le sample restant est dans le projet 14669.

Les **47** samples ambigus sont conservés comme tels ; ils ne sont pas forcés dans une zone arbitraire. Ils proviennent des projets 3068, 11469, 14622 et 18084.

## Métadonnées incomplètes

Les champs station/cruise/profile ne sont pas fournis pour tous les projets par EcoTaxa :

- station manquante : 2 755 samples
- cruise manquante : 2 841 samples
- profile manquant : 2 847 samples

Ces valeurs nulles sont des absences dans la réponse source, pas des valeurs inventées par le chargeur.

## Conclusion

Le chargement projet/sample est cohérent et complet pour les 23 projets accessibles. Les zones et les métadonnées absentes restent explicitement qualifiées ; aucune correction silencieuse ne doit être appliquée avant de poursuivre avec EcoPart et CTD.

## Enrichissement objets et dates

- Objets attendus d'après les compteurs projet : **15 050 002**
- Objets présents dans `warehouse.ecotaxa_object` : **15 050 002**
- Objets avec `object_datetime` : **15 042 600**
- Samples avec `datetime_min/max` : **6 137 / 6 138**
- Doublons `(sample_id, object_id)` : **0**

Le seul sample sans date est `11469000007` (`__DUMMY_ID__1298__`), dont les objets source n'ont pas de `objdate` exploitable. La période couverte par les dates disponibles va du **1987-06-27** au **2025-07-07**.

## CTD Amundsen

- Profils CTD chargés : **456** (2016, 2021, 2023 et 2024)
- Mesures CTD : **5 130 421**
- Références `ctd_rosette_filename` inspectées : **1 019**
- Samples EcoTaxa reliés : **904**
- Relation utilisée : `filename_exact`, fondée sur le nom direct ou sur la
  résolution contrôlée date + position pour les codes courts 2023/2024.

Les **115** références restantes sont conservées dans EcoTaxa sans lien CTD
forcé. Elles comprennent notamment la campagne Champlain 2022 (source non
Amundsen) et des fichiers courts ou des campagnes qui ne sont pas présents dans
le jeu Amundsen interrogé.

### Couverture CTD

- Samples EcoTaxa totaux : **6 138**
- Samples avec un lien CTD : **904**, soit **14,73 %**
- Profils UVP EcoTaxa distincts avec un lien CTD : **495 sur 700**
- Pour les campagnes Amundsen 2021–2024 déjà couvertes : **297 samples sur
  395** (**75,19 %**)
- Projet Amundsen 2025 `17808` : **0/11** tant que la source CTD 2025 n'est
  pas publiée.
