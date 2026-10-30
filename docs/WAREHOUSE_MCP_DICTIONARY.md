# Dictionnaire des vues accessibles via MCP

Généré depuis le schéma déployé et le dictionnaire métier versionné. Les données restent à qualifier.

Dans DbHub : appeler `warehouse_context` avec `topic="overview"`, puis le nom de vue.
`topic="all"` retourne toutes les fiches. Types et SQL réels : `explore.warehouse_dictionary`.

Warehouse NeoLab : EcoTaxa (objets/annotations), EcoPart (profils/bins/volumes), FILET (échantillons/analyses/abondances et biomasses source), CTD (mesures environnementales). Lire ce contexte puis demander la fiche de chaque vue utilisée avec warehouse_context(topic=nom). Avant de produire un graphique, lire warehouse_context(topic=graphs) pour les bibliothèques, le style, les règles scientifiques, la provenance et les exports. Les métadonnées et vues existent même quand les données sont absentes : lire explore.dataset_versions et mesurer la couverture avant de conclure. Ne pas inventer données, unités, taxons, liens ou validation scientifique. Ne pas interpréter biologiquement les résultats. NULL signifie absent/inconnu; zéro et absence de ligne sont différents. Garder source, versions, politiques d’annotation, stades et dénominateurs explicites. Ne pas sommer les volumes répétés par taxon ou les concentrations FILET répétées par bin. Les fichiers sources bruts ne sont pas modifiés. Accès MCP : SELECT explore uniquement, sans écriture ni DDL, délai 30 s. Le périmètre de chaque compte (contrats, zones, années) est dans explore.my_access; explore.my_datasets dit pour chaque version si l'accès est complet, partiel ou nul et pourquoi. Un résultat vide peut signifier un accès limité, pas une absence de données : consulter my_datasets avant de conclure. Les vues UVP joignent EcoTaxa et EcoPart et exigent un droit sur les deux. Avec un accès partiel, une colonne issue d'une jointure externe peut être NULL parce que la ligne liée est hors périmètre. explore.dataset_catalog décrit toutes les versions, même hors périmètre, et explore.fair_readiness mesure la complétude des métadonnées. Priorité absolue : récupérer l'intégralité des données nécessaires avant toute analyse. Chaque réponse SQL est plafonnée (DbHub : 1 000 lignes; la réponse brute porte un champ truncated). Compter d'abord avec count(*), puis agréger côté SQL (SUM/AVG/GROUP BY) ou paginer par tri stable (ORDER BY clé + LIMIT/OFFSET) jusqu'à couvrir le total attendu. Pour une extraction brute qui dépasse la limite, vérifier la complétude par un hash ou un compte recalculé côté base après coup, pas seulement en confiance. Ne jamais présenter une page partielle comme le résultat complet. Une fois les données entièrement récupérées, aucune restriction supplémentaire : les croiser, les agréger, les visualiser et les calculer librement avec les outils disponibles (pandas, Matplotlib, Cartopy, etc.) sans demander de confirmation additionnelle pour l'analyse elle-même. Le navigateur sur 127.0.0.1:8090 et le MCP sont deux accès distincts. Le filtre spatial du navigateur réduit les paires déjà enregistrées, sans changer leur statut. Les confirmations restent nécessaires avant téléchargement/calcul lourd. Répondre en français; expliciter résultat, source, méthode et limites.

## Règles de graphiques — topic=graphs

**Bibliothèques :** Règles de graphiques NeoLab. Utiliser Python : pandas pour manipuler les résultats SQL, Matplotlib pour les figures scientifiques statiques; seaborn facultatif pour les distributions. Cartopy avec Matplotlib pour les cartes statiques et projections; Folium pour les cartes interactives exportées en HTML. GeoPandas/Shapely/pyproj seulement si des opérations de géométrie ou de reprojection sont nécessaires. cmocean pour les palettes de variables océanographiques, avec barre de couleur et unités explicites; conserver cividis en repli. Pour l’analyse physique océanographique : oceans fournit des utilitaires, gsw (GSW/TEOS-10) les propriétés thermodynamiques; xarray convient aux données multidimensionnelles/NetCDF. Ces bibliothèques sont facultatives selon le besoin; ne pas les installer ni les appeler toutes systématiquement. Vérifier pour chaque fonction les entrées requises, unités, convention scientifique et domaine de validité; toute grandeur dérivée conserve formule et provenance. Avec gsw, distinguer salinité pratique/absolue et température in situ/conservative; ne pas substituer directement pression et profondeur. Clarifier les hypothèses manquantes avant calcul. Plotly uniquement si une interaction est demandée ou utile à une exploration explicitée; fournir alors un HTML autonome. Vérifier les bibliothèques installées avant exécution; leur mention ici ne signifie pas qu’elles sont disponibles. Respecter un choix explicite de l’utilisateur.

**Données et calcul :** Le graphique représente le grain documenté et un résultat réellement calculé. Agréger dans SQL avant transfert. DbHub limite les réponses à 1 000 lignes : contrôler le nombre attendu et toute indication de résultat tronqué; ne jamais tracer un sous-ensemble tronqué comme une population complète. Une base vide produit un constat d’absence de données, aucun graphique avec données inventées. NULL et zéro restent distincts. Ne pas interpoler, lisser, normaliser ou exclure des valeurs sans méthode explicite; demander une clarification si cela change le sens scientifique.

**Style :** Style par défaut : fond blanc, police DejaVu Sans 11 pt, titre descriptif court en français, axes avec noms et unités vérifiées, légende lisible, grille fine gris clair et marges sans texte coupé. Couleurs catégorielles adaptées au daltonisme, palette séquentielle cividis pour une quantité continue. Conserver couleurs et échelles cohérentes entre panneaux comparables. Pas de 3D décorative ou double axe sans justification. Profils : profondeur en ordonnée croissante vers le bas; échelle logarithmique uniquement explicitée et compatible avec zéros/valeurs négatives. Conserver les deux dénominateurs FILET séparés et appliquer l’agrégation UVP pondérée par volume. Cartographie : vérifier le CRS; les coordonnées du warehouse sont en degrés WGS84. Avec Cartopy, séparer projection d’affichage et transform des données : PlateCarree pour les longitudes/latitudes WGS84, projection polaire adaptée à l’Arctique si pertinente. Ordre des points : Cartopy (longitude, latitude), Folium [latitude, longitude], GeoJSON [longitude, latitude]. Exclure explicitement les coordonnées manquantes/hors domaine sans les inventer. Calculer les distances en géodésique/PostGIS, pas en degrés ni en pixels. Conserver la version des zones et les ambiguïtés; distinguer source, statut et concentration dans la légende. Identifier les fonds/tuiles et leurs attributions. Les tuiles, bibliothèques JavaScript distantes et fonds Cartopy peuvent nécessiter Internet ou un cache local : ne pas annoncer une carte Folium autonome hors ligne sans l’avoir vérifiée. Privilégier les fonds locaux/caches; confirmer tout téléchargement lourd.

**Statut et livraison :** Afficher un cartouche de statut : Exploratoire par défaut, pas une probabilité de confiance. Convention confirmed (#007B88, trait plein), exploratory (#B87514, tirets), uncertain (#737C86, pointillés); toujours ajouter un libellé ou symbole pour ne pas dépendre de la couleur. confirmed exige une validation scientifique explicitement documentée; un match accepted ou un test technique réussi ne suffit pas. uncertain signale les limites connues, sans inventer de valeurs ou d’intervalles. Si la couleur code un taxon ou une quantité, garder le statut dans le cartouche et les libellés. Aucune interprétation biologique, aucun ajustement statistique ni intervalle d’incertitude inventé. Conserver requête SQL, paramètres, versions, méthode, exclusions et limites dans un fichier de provenance accompagnant la figure. Produire un PNG à 300 dpi et un SVG pour les figures statiques, le CSV exact tracé et le script Python reproductible; indiquer les chemins réels des fichiers créés. Inspecter le rendu avant livraison et signaler toute limite restante.

## explore.uvp_projects

Inventaire agrégé des projets UVP liés à EcoTaxa/EcoPart.

**Grain :** Projet EcoTaxa × projet EcoPart × campagne; EcoTaxa peut être NULL.

**Relations :** Navigation vers uvp_samples par ecotaxa_project_id et ecopart_project_id; sélectionner la campagne.

**Limites :** Ne pas sommer des projets qui réutilisent les mêmes profils. La zone MIN est un libellé représentatif, pas toute la couverture. Pas de dataset_version_id dans cette vue : auditer les versions dans dataset_versions et les vues détaillées.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| start_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| end_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| n_profiles | bigint | Nombre de profils UVP DISTINCT dans le groupe; groupes potentiellement chevauchants. |
| n_ecotaxa_samples | bigint | Nombre de samples EcoTaxa DISTINCT dans le groupe. |
| n_casts | bigint | Nombre de clés de cast DISTINCT non NULL dans le groupe. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| latitude_min | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| latitude_max | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude_min | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude_max | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |

```sql
SELECT * FROM explore.uvp_projects LIMIT 20;
```

## explore.uvp_samples

Métadonnées des profils UVP liés à un sample EcoTaxa.

**Grain :** Profil UVP × liaison sample EcoTaxa; plusieurs liaisons par profil possibles.

**Relations :** uvp_profile_id = uvp_taxon_abundance.profile_id ou ecopart_bins.profile_id; ecotaxa_sample_id = ecotaxa_ctd_profile.ecotaxa_sample_id.

**Limites :** INNER JOIN : les profils sans sample EcoTaxa lié sont absents. COUNT(DISTINCT uvp_profile_id) pour compter les profils. Les zones préfèrent EcoTaxa puis EcoPart.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| ecopart_sample_id | text | Identifiant natif du sample EcoPart, si fourni. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| cast_key | text | Identifiant/libellé de cast du profil UVP. |
| sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| ecotaxa_native_sample_id | text | Identifiant natif du sample EcoTaxa; qualifier par projet/version. |
| sample_orig_id | text | Identifiant original du sample EcoTaxa, utilisé par les liens de provenance. |
| ecotaxa_profile_id | text | Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP. |
| ctd_rosette_filename | text | Nom source de fichier rosette CTD; indice de correspondance, pas une preuve unique suffisante. |
| datetime_min | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| datetime_max | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| depth_min | double precision | Borne de profondeur fournie dans les métadonnées EcoTaxa; unité à vérifier dans la source. |
| depth_max | double precision | Borne de profondeur fournie dans les métadonnées EcoTaxa; unité à vérifier dans la source. |
| instrument | text | Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_source | text | Référentiel utilisé pour l’attribution de zone. |
| marine_zone_version | text | Version du référentiel ou de l’attribution de zone. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| object_count | bigint | Nombre d’objets déclaré par les métadonnées source, pas un recomptage de tous les objets chargés. |
| nb_validated | bigint | Nombre validé déclaré dans les métadonnées EcoTaxa; ne qualifie pas chaque objet chargé. |
| nb_predicted | bigint | Nombre prédit déclaré dans les métadonnées EcoTaxa. |
| nb_dubious | bigint | Nombre douteux déclaré dans les métadonnées EcoTaxa. |
| nb_unclassified | bigint | Nombre non classé déclaré dans les métadonnées EcoTaxa. |

```sql
SELECT uvp_profile_id,sample_name,station_key,sampled_at FROM explore.uvp_samples LIMIT 20;
```

## explore.uvp_objects

Objets EcoTaxa associés aux profils UVP, avec un bin EcoPart éventuel.

**Grain :** Profil UVP × objet EcoTaxa × correspondance de bin éventuelle.

**Relations :** uvp_profile_id vers uvp_samples; uvp_bin_id vers ecopart_bins.bin_id. ecotaxa_object_id est la clé technique de l’objet.

**Limites :** Les jointures peuvent multiplier les objets : compter DISTINCT ecotaxa_object_id au périmètre choisi. Un bin NULL ne signifie pas volume nul. Ne pas joindre les objets à tous les scans CTD du profil. taxon_id/taxon_name/annotation_status peuvent manquer; aucune validation taxonomique implicite.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_version | text | Version du référentiel ou de l’attribution de zone. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| sample_orig_id | text | Identifiant original du sample EcoTaxa, utilisé par les liens de provenance. |
| ecotaxa_object_id | bigint | Clé technique de l’objet EcoTaxa; utiliser DISTINCT si une jointure peut multiplier ses lignes. |
| object_id | text | Identifiant natif de l’objet EcoTaxa, qualifié par son sample/source. |
| acquisition_id | text | Identifiant natif d’acquisition EcoTaxa. |
| process_id | text | Identifiant natif de traitement EcoTaxa. |
| taxon_id | text | Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite. |
| taxon_name | text | Libellé taxonomique EcoTaxa fourni; ne prouve pas un mapping FILET ni une validation. |
| annotation_status | text | Statut d’annotation EcoTaxa chargé; NULL signifie inconnu, pas validated. |
| object_depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| object_depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| uvp_bin_id | bigint | Clé technique du bin EcoPart lié à l’objet; NULL si non apparié. |
| source_bin_key | text | Identifiant du bin dans l’export source. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| depth_delta_m | numeric | Écart vertical enregistré pour l’association objet–bin, en mètres. |
| mapping_method | text | Méthode d’association objet–bin EcoPart. |
| mapping_status | text | Statut de l’association objet–bin; distinct du statut d’annotation taxonomique. |
| image_uri | text | Référence d’image source de l’objet; sa présence ne garantit pas l’accessibilité de l’image. |

```sql
SELECT taxon_id,taxon_name,COUNT(DISTINCT ecotaxa_object_id) FROM explore.uvp_objects GROUP BY 1,2 LIMIT 20;
```

## explore.ecopart_bins

Bins échantillonnés EcoPart, y compris sans objet, et ligne brute PAR.

**Grain :** Version EcoPart × profil × bin disposant d’une ligne source.

**Relations :** profile_id vers uvp_samples.uvp_profile_id; bin_id vers uvp_taxon_abundance.bin_id.

**Limites :** Conserver les bins sans objet dans le dénominateur. source_row_json conserve les champs et unités sources : ne pas inférer leur unité à partir du nom seul.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| profile_id | bigint | Clé technique du profil UVP; équivaut à uvp_samples.uvp_profile_id. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| bin_id | bigint | Clé technique du bin EcoPart. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| source_depth_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| source_row_json | jsonb | Ligne source complète conservée en JSON; noms et unités non harmonisés. Inspecter avant calcul. |

```sql
SELECT profile_id,bin_id,depth_min_m,depth_max_m,sampled_volume_l FROM explore.ecopart_bins LIMIT 20;
```

## explore.uvp_taxon_abundance

Abondances UVP dérivées des objets EcoTaxa et volumes EcoPart.

**Grain :** Version dérivée × profil × bin × taxon_key × annotation_policy.

**Relations :** profile_id vers uvp_samples.uvp_profile_id; bin_id vers ecopart_bins.bin_id. Isoler annotation_policy et dataset_version_id.

**Limites :** Formule : n_objects_taxon / sampled_volume_l × 1000, individus/m³. Agréger par SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000, pas par moyenne simple. La vue ajoute des zéros sur tous les bins uniquement pour les taxons observés dans ce profil et cette annotation_policy; un taxon absent du profil entier ne reçoit pas de zéro. all_loaded_objects inclut les objets non validés. Ne pas sommer le même volume sur plusieurs taxons.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| profile_id | bigint | Clé technique du profil UVP; équivaut à uvp_samples.uvp_profile_id. |
| bin_id | bigint | Clé technique du bin EcoPart. |
| taxon_key | text | Clé dérivée : ecotaxa:id:…, ecotaxa:name:… ou warehouse:unclassified; ne pas présenter un libellé ou marqueur comme identifiant taxonomique officiel. |
| annotation_policy | text | Politique de sélection des objets et projet EcoTaxa; all_loaded_objects inclut tous les objets chargés, pas uniquement les validés. |
| n_objects_taxon | bigint | Nombre d’objets du taxon pour le bin et la politique; zéros densifiés selon le contrat de la vue. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| abundance_uvp_ind_m3 | numeric | Abondance UVP dérivée en individus/m³ : n_objects_taxon / sampled_volume_l × 1000. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |

```sql
SELECT profile_id,taxon_key,annotation_policy,SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000 AS ind_m3 FROM explore.uvp_taxon_abundance GROUP BY 1,2,3 LIMIT 20;
```

## explore.uvp_particle_sizes

Spectre de tailles des particules UVP (produit EcoPart LPM), sans annotation taxonomique.

**Grain :** Profil × bin (profondeur) × size_class_key.

**Relations :** uvp_profile_id vers uvp_samples.uvp_profile_id; uvp_bin_id vers le bin de profondeur. Grain distinct de uvp_taxon_abundance : pas de taxon_key, pas de correspondance directe avec une espèce ou un stade.

**Limites :** sampled_volume_l est un attribut du bin, répété sur chaque size_class_key de ce bin : sommer ce volume directement sur plusieurs classes de taille le compte une fois par classe au lieu d’une fois par bin, et fausse la densité (division par un volume trop grand). Pour une densité sur une gamme de taille, agréger le volume une seule fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id), sommer particle_count et ce volume par bin sur les size_class_key choisies, puis diviser et ×1000 pour des particules/m³; ne pas mélanger des bins de profondeur différente dans une même somme sans le dire. particle_count et observed_volume_m3 sont les valeurs source, non recalculées. Ne pas comparer directement à une abondance taxonomique FILET ou UVP : la comparaison porte sur une taille, pas une identification.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| uvp_bin_id | bigint | Clé technique du bin EcoPart lié à l’objet; NULL si non apparié. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| size_class_key | text | Clé de classe de taille EcoPart (produit LPM); grain non taxonomique, distinct de taxon_key. |
| size_min_um | double precision | Borne inférieure de la classe de taille, en micromètres; définit la gamme avec size_max_um. |
| size_max_um | double precision | Borne supérieure de la classe de taille, en micromètres; définit la gamme avec size_min_um. |
| size_definition | text | Méthode ou convention EcoPart ayant défini les bornes de taille; ne pas supposer une convention unique entre jeux de données. |
| particle_count | bigint | Nombre brut de particules comptées pour la classe de taille et le bin; valeur source, non recalculée. |
| observed_volume_m3 | double precision | Volume observé par l’instrument pour ce bin, en m³; distinct de sampled_volume_l. |
| supplied_concentration | double precision | Concentration fournie par EcoPart pour la classe de taille, si présente; ne pas la substituer à un calcul propre sans vérifier son unité. |
| concentration_unit | text | Unité de supplied_concentration telle que fournie par EcoPart; vérifier avant toute comparaison entre jeux de données. |

```sql
WITH per_bin AS (SELECT uvp_bin_id, MIN(sampled_volume_l) AS vol_l, SUM(particle_count) AS n FROM explore.uvp_particle_sizes WHERE size_min_um>=200 AND size_max_um<=1000 GROUP BY uvp_bin_id) SELECT SUM(n)/SUM(vol_l)*1000 AS n_m3 FROM per_bin;
```

## explore.ecopart_source_metadata

Lignes brutes des métadonnées EcoPart.

**Grain :** Ligne source de métadonnées dans une version et un profil éventuel.

**Relations :** dataset_version_id vers dataset_versions; profile_name correspond au nom natif, pas à une clé globale.

**Limites :** Le grain source member_name/row_number n’est pas exposé : des lignes du même profil peuvent exister. Ne pas enrichir EcoTaxa sans liaison prouvée. Unités dans la source JSON, non harmonisées.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| profile_name | text | Nom du profil dans la ligne source EcoPart; peut être absent ou répété. |
| source_row_json | jsonb | Ligne source complète conservée en JSON; noms et unités non harmonisés. Inspecter avant calcul. |

```sql
SELECT * FROM explore.ecopart_source_metadata LIMIT 5;
```

## explore.ecopart_supplied_zooplankton

Lignes ZOO fournies par EcoPart, conservées sans recalcul.

**Grain :** Ligne source ZOO dans une version et un profil éventuel.

**Relations :** dataset_version_id vers dataset_versions; profile_name doit être qualifié par sa source/version.

**Limites :** Ne pas confondre ces données fournies avec uvp_taxon_abundance : les exports ZOO peuvent utiliser les vignettes validées, contrairement à all_loaded_objects. Inspecter les champs/unités JSON avant calcul.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| profile_name | text | Nom du profil dans la ligne source EcoPart; peut être absent ou répété. |
| source_row_json | jsonb | Ligne source complète conservée en JSON; noms et unités non harmonisés. Inspecter avant calcul. |

```sql
SELECT * FROM explore.ecopart_supplied_zooplankton LIMIT 5;
```

## explore.uvp_ctd

Mesures CTD rattachées à un profil UVP.

**Grain :** Liaison UVP–CTD × ligne/scan source × variable × canal.

**Relations :** uvp_profile_id vers uvp_samples; ctd_profile_id identifie le profil CTD. Ne pas aligner verticalement par le seul profil.

**Limites :** La présence d’une liaison ne prouve pas l’alignement profondeur/temps de chaque mesure. Valeur/unité/QC doivent être lus ensemble. Ne pas multiplier ces lignes par les objets du profil.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| uvp_dataset_version_id | bigint | Version de la source du profil UVP; distincte de la version CTD. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| ecopart_sample_id | text | Identifiant natif du sample EcoPart, si fourni. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| ctd_dataset_version_id | bigint | Version de la source du profil CTD. |
| ctd_source_profile_key | text | Identifiant natif du profil CTD. |
| source_row_key | text | Clé de ligne source CTD; conserve le grain original. |
| scan_key | text | Identifiant de scan source CTD; qualifier par profil et source. |
| depth_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| pressure_dbar | double precision | Pression CTD en dbar; ne pas assimiler automatiquement à la profondeur en mètres. |
| variable_key | text | Code de variable CTD; conserver les codes source et ne pas assimiler des variables sans vérifier définition/unité. |
| variable_definition | text | Définition source de la variable CTD. |
| sensor_channel | text | Canal/capteur source CTD; deux canaux ne sont pas des répétitions à moyenner implicitement. |
| value | double precision | Valeur CTD fournie; interpréter avec unit, variable_key, sensor_channel et qc. |
| unit | text | Unité CTD fournie; aucune conversion implicite entre codes/sources. |
| qc | text | Indicateur qualité source CTD; NULL signifie absent, pas bon. |

```sql
SELECT sample_name,depth_m,variable_key,value,unit,qc FROM explore.uvp_ctd LIMIT 20;
```

## explore.ecotaxa_ctd_profile

Liens EcoTaxa–CTD et preuves, y compris non acceptés.

**Grain :** Sample EcoTaxa × profil CTD candidat.

**Relations :** ecotaxa_sample_id vers uvp_samples; ctd_profile_id vers ecotaxa_ctd.

**Limites :** Filtrer match_status selon l’usage; candidat et ambigu ne sont pas des liens acceptés. Consulter relation_type, distance_km, time_gap_minutes et evidence.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_native_sample_id | text | Identifiant natif du sample EcoTaxa; qualifier par projet/version. |
| sample_orig_id | text | Identifiant original du sample EcoTaxa, utilisé par les liens de provenance. |
| ecotaxa_profile_id | text | Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP. |
| ecotaxa_station_id | text | Station fournie dans les métadonnées EcoTaxa. |
| ecotaxa_cruise_id | text | Campagne fournie dans les métadonnées EcoTaxa. |
| ctd_rosette_filename | text | Nom source de fichier rosette CTD; indice de correspondance, pas une preuve unique suffisante. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| source_profile_key | text | Identifiant natif du profil CTD. |
| ctd_station_id | text | Clé de station du profil CTD. |
| ctd_sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| relation_type | text | Nature de la liaison EcoTaxa–CTD déclarée par le rapprochement. |
| match_status | text | Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés. |
| distance_km | numeric | Écart spatial enregistré du lien EcoTaxa–CTD, en kilomètres; pas le seuil spatial FILET–UVP du navigateur. |
| time_gap_minutes | numeric | Écart temporel enregistré du lien EcoTaxa–CTD, en minutes. |
| evidence | text | Preuves de correspondance JSON; conserver les paramètres, sources et éventuelles ambiguïtés. |

```sql
SELECT ecotaxa_sample_id,ctd_profile_id,match_status,distance_km,time_gap_minutes FROM explore.ecotaxa_ctd_profile LIMIT 20;
```

## explore.ecotaxa_ctd

Mesures CTD des seuls liens EcoTaxa–CTD acceptés.

**Grain :** Sample EcoTaxa × profil CTD accepté × mesure/variable/canal.

**Relations :** ecotaxa_sample_id vers uvp_samples; ctd_profile_id vers ecotaxa_ctd_profile.

**Limites :** Le lien est filtré accepted, mais pas le QC des valeurs. Cette vue n’expose pas toutes les clés source de scan; ne pas supposer une clé unique (profondeur,variable). Aligner verticalement avec une méthode explicite.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_native_sample_id | text | Identifiant natif du sample EcoTaxa; qualifier par projet/version. |
| sample_orig_id | text | Identifiant original du sample EcoTaxa, utilisé par les liens de provenance. |
| ecotaxa_profile_id | text | Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP. |
| ecotaxa_station_id | text | Station fournie dans les métadonnées EcoTaxa. |
| ecotaxa_cruise_id | text | Campagne fournie dans les métadonnées EcoTaxa. |
| ctd_rosette_filename | text | Nom source de fichier rosette CTD; indice de correspondance, pas une preuve unique suffisante. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| source_profile_key | text | Identifiant natif du profil CTD. |
| ctd_station_id | text | Clé de station du profil CTD. |
| ctd_sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| relation_type | text | Nature de la liaison EcoTaxa–CTD déclarée par le rapprochement. |
| match_status | text | Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés. |
| distance_km | numeric | Écart spatial enregistré du lien EcoTaxa–CTD, en kilomètres; pas le seuil spatial FILET–UVP du navigateur. |
| time_gap_minutes | numeric | Écart temporel enregistré du lien EcoTaxa–CTD, en minutes. |
| evidence | text | Preuves de correspondance JSON; conserver les paramètres, sources et éventuelles ambiguïtés. |
| depth_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| pressure_dbar | double precision | Pression CTD en dbar; ne pas assimiler automatiquement à la profondeur en mètres. |
| variable_key | text | Code de variable CTD; conserver les codes source et ne pas assimiler des variables sans vérifier définition/unité. |
| variable_definition | text | Définition source de la variable CTD. |
| sensor_channel | text | Canal/capteur source CTD; deux canaux ne sont pas des répétitions à moyenner implicitement. |
| value | double precision | Valeur CTD fournie; interpréter avec unit, variable_key, sensor_channel et qc. |
| unit | text | Unité CTD fournie; aucune conversion implicite entre codes/sources. |
| qc | text | Indicateur qualité source CTD; NULL signifie absent, pas bon. |

```sql
SELECT ecotaxa_sample_id,depth_m,variable_key,value,unit,qc FROM explore.ecotaxa_ctd LIMIT 20;
```

## explore.filet_samples

Métadonnées des échantillons FILET et nombre d’analyses.

**Grain :** Échantillon FILET technique, dans une version.

**Relations :** id = filet_uvp_matches.filet_sample_id. sample_id natif se qualifie par dataset_version_id.

**Limites :** Un échantillon peut avoir plusieurs analyses ou filets. Zone ambiguous peut signifier chevauchement de polygones, pas exclusion spatiale. Ne pas assimiler station FILET et station UVP par identifiant.

| Colonne | Type SQL | Définition |
|---|---|---|
| id | bigint | Clé technique de l’échantillon FILET. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| sample_id | text | Identifiant natif du sample FILET; qualifier par version. |
| deployment_id | text | Identifiant natif de déploiement FILET. |
| sampling_year | integer | Année de prélèvement fournie dans les métadonnées FILET. |
| sampling_platform | text | Plateforme de prélèvement fournie par la source FILET. |
| station_name | text | Libellé de station FILET fourni par la source. |
| deployment_datetime_start | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| deployment_datetime_end | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| cast_number | text | Numéro de cast fourni dans les métadonnées FILET. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_source | text | Référentiel utilisé pour l’attribution de zone. |
| marine_zone_version | text | Version du référentiel ou de l’attribution de zone. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| gear | text | Équipement FILET déclaré par la source. |
| tow_type | text | Type de trait FILET déclaré par la source. |
| min_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| max_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| net_mesh_size | numeric | Maille FILET déclarée; unité à confirmer dans la source avant conversion. |
| depth_calc_net_filtered_vol | numeric | Volume FILET fourni calculé par profondeur; unité à confirmer dans la documentation source avant conversion. |
| flowmeter_calc_vol | numeric | Volume FILET fourni calculé par flowmeter; unité à confirmer dans la source. |
| number_of_nets | integer | Nombre de filets déclaré dans les métadonnées FILET. |
| sample_nets | text | Description source des filets associés à l’échantillon. |
| net_sampling_ids | text | Identifiants de prélèvement/filet fournis; conserver leur représentation source. |
| subsampling_quantity | numeric | Quantité de sous-échantillonnage fournie; lire subsampling_unit. |
| subsampling_unit | text | Unité déclarée du sous-échantillonnage; ne pas la remplacer implicitement. |
| n_analyses | bigint | Nombre d’analyses FILET DISTINCT liées à l’échantillon. |

```sql
SELECT id,sample_id,station_name,latitude,longitude,n_analyses FROM explore.filet_samples LIMIT 20;
```

## explore.filet_data

Abondances et biomasses FILET fournies, avec métadonnées éventuellement non appariées.

**Grain :** Version d’abondance × sample_id × analysis_id × taxon_id × stage; ligne source conservée.

**Relations :** sample_id + metadata_dataset_version_id vers filet_samples.sample_id + dataset_version_id; ne pas utiliser la version d’abondance à la place de la version des métadonnées.

**Limites :** Valeurs source : ne pas recalculer les volumes ou concentrations. Depth et flowmeter restent deux dénominateurs distincts. Ne pas sommer stades détaillés et agrégats; metadata_matched=false garde la ligne sans inventer de coordonnées. analysis_contract est un libellé source, pas une règle validée de séparation.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| source_row_number | integer | Numéro de ligne dans le fichier source FILET, avant dépliage des stades. |
| sample_id | text | Identifiant natif du sample FILET; qualifier par version. |
| analysis_id | text | Identifiant natif d’analyse FILET; qualifier par sample et version. |
| taxon_id | text | Identifiant taxonomique FILET fourni, texte source; pas un AphiaID supposé. |
| stage | text | Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES. |
| is_aggregate | boolean | Vrai pour COPEPODID, NAUPLIUS ou ALL_STAGES; éviter leur double comptage avec les sous-stades. |
| sample_abundance | numeric | Nombre d’individus attribués par la source FILET, déjà calculé; ne pas recalculer implicitement. |
| abundance_depth_ind_m3 | numeric | Abondance FILET source en individus/m³, dénominateur volume depth. |
| abundance_flowmeter_ind_m3 | numeric | Abondance FILET source en individus/m³, dénominateur volume flowmeter. |
| biomass_depth_ug_c_m3 | numeric | Biomasse FILET source en µg C/m³ selon volume depth. |
| biomass_flowmeter_ug_c_m3 | numeric | Biomasse FILET source en µg C/m³ selon volume flowmeter. |
| metadata_dataset_version_id | bigint | Version des métadonnées FILET liées; peut être NULL si aucune métadonnée ne correspond. |
| deployment_id | text | Identifiant natif de déploiement FILET. |
| sampling_year | integer | Année de prélèvement fournie dans les métadonnées FILET. |
| sampling_platform | text | Plateforme de prélèvement fournie par la source FILET. |
| station_name | text | Libellé de station FILET fourni par la source. |
| deployment_datetime_start | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| min_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| max_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| net_mesh_size | numeric | Maille FILET déclarée; unité à confirmer dans la source avant conversion. |
| depth_calc_net_filtered_vol | numeric | Volume FILET fourni calculé par profondeur; unité à confirmer dans la documentation source avant conversion. |
| flowmeter_calc_vol | numeric | Volume FILET fourni calculé par flowmeter; unité à confirmer dans la source. |
| net_sampling_ids | text | Identifiants de prélèvement/filet fournis; conserver leur représentation source. |
| subsampling_quantity | numeric | Quantité de sous-échantillonnage fournie; lire subsampling_unit. |
| subsampling_unit | text | Unité déclarée du sous-échantillonnage; ne pas la remplacer implicitement. |
| analysis_contract | text | Contrat d’analyse FILET fourni; aucune règle métier de séparation des contrats validée. |
| analysis_protocol_id | text | Identifiant source du protocole d’analyse FILET. |
| metadata_matched | boolean | Vrai si la ligne FILET rejoint une analyse/métadonnée; faux conserve la ligne sans inventer de contexte. |

```sql
SELECT sample_id,analysis_id,taxon_id,stage,abundance_depth_ind_m3,abundance_flowmeter_ind_m3,metadata_matched FROM explore.filet_data LIMIT 20;
```

## explore.filet_totals

Sous-ensemble FILET au stade ALL_STAGES.

**Grain :** Même grain que filet_data, limité à stage=ALL_STAGES.

**Relations :** Même contrat de jointure et de versions que filet_data.

**Limites :** Ne pas additionner ALL_STAGES avec les sous-stades. Ne pas mélanger depth et flowmeter. Un total fourni n’autorise pas une équivalence taxonomique avec UVP.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| source_row_number | integer | Numéro de ligne dans le fichier source FILET, avant dépliage des stades. |
| sample_id | text | Identifiant natif du sample FILET; qualifier par version. |
| analysis_id | text | Identifiant natif d’analyse FILET; qualifier par sample et version. |
| taxon_id | text | Identifiant taxonomique FILET fourni, texte source; pas un AphiaID supposé. |
| stage | text | Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES. |
| is_aggregate | boolean | Vrai pour COPEPODID, NAUPLIUS ou ALL_STAGES; éviter leur double comptage avec les sous-stades. |
| sample_abundance | numeric | Nombre d’individus attribués par la source FILET, déjà calculé; ne pas recalculer implicitement. |
| abundance_depth_ind_m3 | numeric | Abondance FILET source en individus/m³, dénominateur volume depth. |
| abundance_flowmeter_ind_m3 | numeric | Abondance FILET source en individus/m³, dénominateur volume flowmeter. |
| biomass_depth_ug_c_m3 | numeric | Biomasse FILET source en µg C/m³ selon volume depth. |
| biomass_flowmeter_ug_c_m3 | numeric | Biomasse FILET source en µg C/m³ selon volume flowmeter. |
| metadata_dataset_version_id | bigint | Version des métadonnées FILET liées; peut être NULL si aucune métadonnée ne correspond. |
| deployment_id | text | Identifiant natif de déploiement FILET. |
| sampling_year | integer | Année de prélèvement fournie dans les métadonnées FILET. |
| sampling_platform | text | Plateforme de prélèvement fournie par la source FILET. |
| station_name | text | Libellé de station FILET fourni par la source. |
| deployment_datetime_start | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| min_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| max_sample_depth | numeric | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| net_mesh_size | numeric | Maille FILET déclarée; unité à confirmer dans la source avant conversion. |
| depth_calc_net_filtered_vol | numeric | Volume FILET fourni calculé par profondeur; unité à confirmer dans la documentation source avant conversion. |
| flowmeter_calc_vol | numeric | Volume FILET fourni calculé par flowmeter; unité à confirmer dans la source. |
| net_sampling_ids | text | Identifiants de prélèvement/filet fournis; conserver leur représentation source. |
| subsampling_quantity | numeric | Quantité de sous-échantillonnage fournie; lire subsampling_unit. |
| subsampling_unit | text | Unité déclarée du sous-échantillonnage; ne pas la remplacer implicitement. |
| analysis_contract | text | Contrat d’analyse FILET fourni; aucune règle métier de séparation des contrats validée. |
| analysis_protocol_id | text | Identifiant source du protocole d’analyse FILET. |
| metadata_matched | boolean | Vrai si la ligne FILET rejoint une analyse/métadonnée; faux conserve la ligne sans inventer de contexte. |

```sql
SELECT sample_id,taxon_id,abundance_depth_ind_m3 FROM explore.filet_totals LIMIT 20;
```

## explore.filet_ctd

Mesures CTD rattachées aux échantillons FILET.

**Grain :** Sample FILET natif × liaison CTD × mesure.

**Relations :** filet_sample_id est ici le sample_id NATIF texte; dans filet_uvp_matches, filet_sample_id est au contraire la clé technique bigint. Qualifier les versions via les vues sources avant jointure.

**Limites :** Pas de statut de liaison ni de dataset_version_id exposé : ne pas inférer une validation de correspondance ou une unicité inter-version. Lire unit et qc; pas d’alignement vertical implicite.

| Colonne | Type SQL | Définition |
|---|---|---|
| filet_sample_id | text | Identifiant NATIF texte du sample FILET; pas filet_samples.id. |
| station_name | text | Libellé de station FILET fourni par la source. |
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| source_profile_key | text | Identifiant natif du profil CTD. |
| depth_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| pressure_dbar | double precision | Pression CTD en dbar; ne pas assimiler automatiquement à la profondeur en mètres. |
| variable_key | text | Code de variable CTD; conserver les codes source et ne pas assimiler des variables sans vérifier définition/unité. |
| value | double precision | Valeur CTD fournie; interpréter avec unit, variable_key, sensor_channel et qc. |
| unit | text | Unité CTD fournie; aucune conversion implicite entre codes/sources. |
| qc | text | Indicateur qualité source CTD; NULL signifie absent, pas bon. |

```sql
SELECT filet_sample_id,ctd_profile_id,depth_m,variable_key,value,unit FROM explore.filet_ctd LIMIT 20;
```

## explore.filet_uvp_matches

Correspondances FILET–UVP stockées, avec statut et preuves.

**Grain :** Version de rapprochement × candidat FILET–UVP, analyse FILET éventuellement NULL.

**Relations :** filet_sample_id = filet_samples.id; uvp_profile_id = uvp_samples.uvp_profile_id. filet_analysis_id est une clé technique d’analyse, pas analysis_id natif.

**Limites :** Conserver match_status/evidence; ne pas promouvoir un candidat ambigu en accepted après filtrage. Le navigateur filtre ces paires existantes par heure et distance géodésique; il ne crée pas de candidats. La distance spatiale du navigateur n’est pas une colonne de cette vue. Une fenêtre élargie ne récupère pas des paires jamais chargées.

| Colonne | Type SQL | Définition |
|---|---|---|
| id | bigint | Clé technique de la correspondance FILET–UVP. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| station_id | text | Station déclarée pour le rapprochement; consulter match_method et evidence. |
| filet_sample_id | bigint | Clé TECHNIQUE de l’échantillon FILET : filet_samples.id. |
| filet_analysis_id | bigint | Clé technique d’analyse FILET; NULL si rapprochement sans analyse. |
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| filet_sampled_at | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| uvp_sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| time_gap_hours | numeric | Écart temporel FILET–UVP enregistré, en heures. |
| match_status | text | Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés. |
| match_method | text | Méthode enregistrée de rapprochement; ne pas la déduire du seul statut. |
| evidence | text | Preuves de correspondance JSON; conserver les paramètres, sources et éventuelles ambiguïtés. |

```sql
SELECT id,filet_sample_id,uvp_profile_id,time_gap_hours,match_status FROM explore.filet_uvp_matches WHERE match_status='accepted' LIMIT 20;
```

## explore.filet_uvp_abundance

Comparaison des abondances via les liens FILET–UVP et le mapping taxonomique accepté.

**Grain :** Correspondance × ligne FILET/stade × mapping taxonomique × bin UVP; pas une paire unique.

**Relations :** match_id vers filet_uvp_matches.id; uvp_profile_id vers uvp_samples.uvp_profile_id. Les taxons passent par warehouse.taxon_mapping accepted.

**Limites :** La vue ne filtre PAS m.match_status : exiger accepted si nécessaire. La jointure FILET par identifiants natifs et UVP par profil/taxon n’isole pas toutes les versions ou annotation_policy : risque de multiplication. Le dénominateur FILET est répété par bin UVP; ne pas le sommer. Cette vue n’est pas un comparatif scientifique validé; qualifier versions, profondeur, stades et mapping avant calcul.

| Colonne | Type SQL | Définition |
|---|---|---|
| match_id | bigint | Clé technique de la correspondance FILET–UVP. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| station_id | text | Station déclarée pour le rapprochement; consulter match_method et evidence. |
| filet_sample_id | bigint | Clé TECHNIQUE de l’échantillon FILET : filet_samples.id. |
| filet_analysis_id | bigint | Clé technique d’analyse FILET; NULL si rapprochement sans analyse. |
| uvp_profile_id | bigint | Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances. |
| time_gap_hours | numeric | Écart temporel FILET–UVP enregistré, en heures. |
| match_status | text | Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés. |
| taxon_filet | text | Identifiant taxonomique FILET source du mapping; pas un AphiaID supposé. |
| filet_stage | text | Stade FILET conservé dans la comparaison; ne pas additionner agrégats et détails. |
| abundance_filet_depth_ind_m3 | numeric | Abondance FILET source en individus/m³ selon volume depth; répétée par bin dans la comparaison. |
| abundance_filet_flowmeter_ind_m3 | numeric | Abondance FILET source en individus/m³ selon volume flowmeter; répétée par bin. |
| uvp_taxon | text | Clé taxonomique UVP du mapping accepté; même convention que taxon_key. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| abundance_uvp_ind_m3 | numeric | Abondance UVP dérivée en individus/m³ : n_objects_taxon / sampled_volume_l × 1000. |
| n_objects_taxon | bigint | Nombre d’objets du taxon pour le bin et la politique; zéros densifiés selon le contrat de la vue. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |

```sql
SELECT * FROM explore.filet_uvp_abundance WHERE match_status='accepted' LIMIT 20;
```
