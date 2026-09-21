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

## EcoPart et jointures EcoTaxa — 21 septembre 2026

- Projets EcoPart liés et accessibles : **11**, reliés à **12** projets EcoTaxa. EcoTaxa 149 est relié aux projets EcoPart 86 et 87 ; les projets EcoTaxa 20880 et 20890 réutilisent respectivement ces deux sources.
- Profils EcoPart chargés : **585** ; bins de 5 m : **59 801** ; volumes nuls ou négatifs : **0**.
- Objets EcoTaxa reliés à un bin EcoPart : **10 479 780**. Avec les **228** objets restant sans bin, `explore.uvp_objects` expose **10 480 008** objets EcoTaxa, les non-appariés ayant un bin NULL sans approximation de profondeur.
- La vue `explore.uvp_taxon_abundance` contient **2 703 052** lignes, dont **2 244 582** zéros explicites pour les bins échantillonnés sans objet du taxon considéré. Les dénominateurs conservent donc ces bins.
- Liens UVP → CTD propagés seulement depuis les correspondances EcoTaxa–CTD acceptées : **413** liens pour **413** profils UVP.

Le validateur a comparé les **11** archives EcoPart brutes aux bins chargés : aucun écart de profil, profondeur normalisée ou volume. Les audits SQL suivants retournent tous **0** : objet relié au mauvais sample, profondeur hors bin, plusieurs bins pour un objet dans une même version, formule d'abondance incorrecte, différence entre les comptes d'objets et les abondances, et lien UVP–CTD sans preuve EcoTaxa–CTD acceptée.

Les cinq samples EcoTaxa 149 non liés (`ge_2016_146`, `ge_2016_147`, `ge_2016_148`, `ge_2016_001b`, `ge_2016_002b`) ne figurent dans aucun profil EcoPart exporté et restent non appariés. Les projets EcoTaxa 801, 802, 2331, 3068, 11469, 12063, 13224, 14622, 14669 et 17808 ne retournent pas de lien serveur EcoPart. Le projet 10101 n'a pas été classé : l'endpoint EcoPart `searchsample?filt_proj=10101` n'a pas répondu avant le délai client. Cette absence de réponse ne doit pas être interprétée comme une absence de données.

Les objets EcoTaxa chargés ne portent pas actuellement de statut d'annotation. Les abondances dérivées utilisent donc tous les objets chargés et sont explicitement étiquetées par `annotation_policy`; elles ne sont pas assimilées aux abondances ZOO validées fournies par EcoPart.
