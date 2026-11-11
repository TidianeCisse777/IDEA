# Dictionnaire des vues accessibles via MCP

Généré depuis le schéma déployé et le dictionnaire métier versionné. Les données restent à qualifier.

Dans DbHub : appeler `warehouse_context` avec `topic="overview"`, puis le nom de vue.
`topic="all"` retourne toutes les fiches. Types et SQL réels : `catalogue.warehouse_dictionary`.

Warehouse NeoLab : EcoTaxa (objets/annotations), EcoPart (profils/bins/volumes), FILET (échantillons/analyses/abondances et biomasses source), CTD (mesures environnementales). Lire ce contexte puis demander la fiche de chaque vue utilisée avec warehouse_context(topic=nom). Avant de produire un graphique, lire warehouse_context(topic=graphs) pour les bibliothèques, le style, les règles scientifiques, la provenance et les exports. Les métadonnées et vues existent même quand les données sont absentes : lire catalogue.dataset_versions et mesurer la couverture avant de conclure. Ne pas inventer données, unités, taxons, liens ou validation scientifique. Toute réponse sur les données vient d’une requête execute_sql sur ce warehouse : ne jamais répondre de mémoire ni avec des valeurs générales (climatologie, littérature) à la place des mesures; si une requête échoue ou qu’un outil est refusé, le dire et réessayer avec execute_sql plutôt que d’estimer. Comparer FILET et UVP : explore.filet_uvp_compare(...) et explore.filet_uvp_pairs(...), décrits dans la fiche filet_uvp_abundance et le document filet-uvp-comparaison. Les documents écrits (protocoles, méthodes, notes) sont dans catalogue.documents : les chercher avec search_documents pour une question de méthode, de protocole ou de provenance, et citer doc_key et section. Ne pas interpréter biologiquement les résultats. NULL signifie absent/inconnu; zéro et absence de ligne sont différents. Garder source, versions, politiques d’annotation, stades et dénominateurs explicites. Ne pas sommer les volumes répétés par taxon ou les concentrations FILET répétées par bin. Les fichiers sources bruts ne sont pas modifiés. Accès MCP : SELECT sur deux schémas seulement, explore (les données) et catalogue (droits, catalogue des jeux de données, dictionnaire, ces fiches), sans écriture ni DDL, délai 30 s. Pour une question sur les projets ou les objets EcoTaxa en général, partir de explore.ecotaxa_projects (tous les projets), pas des seules vues uvp_*; dire dans la réponse le périmètre couvert. Pour un taxon (le chercher, le compter, savoir où il est) partir de explore.ecotaxa_sample_taxa, rapide, et non de ecotaxa_objects (15 M lignes, plus de 30 s pour un filtre sur le nom); pour un groupe (« les copépodes »), filtrer la lignée EcoTaxa ('Copepoda' = ANY(taxon_lineage), liste dans explore.ecotaxa_taxa) au lieu d'énumérer des genres de mémoire, et dire quelles catégories non entières ou incertaines (part, cut, dead, eggs, like...) sont gardées. Une demande sans grandeur précise (« le profil vertical », « l'abondance », « le projet ») se lit de plusieurs façons : abondance UVP d'organismes, concentration de particules, ou variable CTD (température, salinité...); dire la grandeur et le projet retenus et pourquoi, ou demander. Un total d'abondance « tous objets » contient surtout des détritus : ne compter comme individus que object_class = 'organism' (explore.ecotaxa_taxa). Explorer avant de générer : n'écrire une requête qu'avec des noms de vues et de colonnes lus dans column_list (cette fiche les donne pour toutes les vues, chaque fiche de vue avec leurs types) ou dans catalogue.warehouse_dictionary; ne jamais deviner un nom (title pour ecotaxa_project_title, explore.zones...) ni sonder une table par essai-erreur. Une erreur SQL renvoyée avec un champ hint dit quoi faire ensuite. Le périmètre de chaque compte (contrats, zones, années) est dans catalogue.my_access; catalogue.my_datasets dit pour chaque version si l'accès est complet, partiel ou nul et pourquoi. Un résultat vide peut signifier un accès limité, pas une absence de données : consulter my_datasets avant de conclure. Les vues UVP joignent EcoTaxa et EcoPart et exigent un droit sur les deux. Avec un accès partiel, une colonne issue d'une jointure externe peut être NULL parce que la ligne liée est hors périmètre. catalogue.dataset_catalog décrit toutes les versions, même hors périmètre, et catalogue.fair_readiness mesure la complétude des métadonnées. Priorité absolue : récupérer l'intégralité des données nécessaires avant toute analyse. Chaque réponse SQL est plafonnée (DbHub : 1 000 lignes; la réponse brute porte un champ truncated). Compter d'abord avec count(*), puis agréger côté SQL (SUM/AVG/GROUP BY) ou paginer par tri stable (ORDER BY clé + LIMIT/OFFSET) jusqu'à couvrir le total attendu. Pour une extraction brute qui dépasse la limite, vérifier la complétude par un hash ou un compte recalculé côté base après coup, pas seulement en confiance. Ne jamais présenter une page partielle comme le résultat complet. Une fois les données entièrement récupérées, aucune restriction supplémentaire : les croiser, les agréger, les visualiser et les calculer librement avec les outils disponibles (pandas, Matplotlib, Cartopy, etc.) sans demander de confirmation additionnelle pour l'analyse elle-même. Le navigateur sur 127.0.0.1:8090 et le MCP sont deux accès distincts. Le filtre spatial du navigateur réduit les paires déjà enregistrées, sans changer leur statut. Les confirmations restent nécessaires avant téléchargement/calcul lourd. Répondre en français; expliciter résultat, source, méthode et limites. Raisonnement : toute réponse qui donne des chiffres ou une figure commence par une courte section « Raisonnement » (quelques puces) : comment la question a été comprise, les choix retenus (projet, grandeur, taxons, profondeur, années, politique d'annotation, catégories exclues) avec leur raison, et les autres lectures possibles écartées; puis le résultat. Chaque chiffre de la réponse vient d'une requête exécutée dans cette conversation; une valeur reprise d'une fiche est signalée comme telle et recalculée si une requête le permet. Transparence pour le chercheur : toute réponse qui donne des chiffres se termine par une section « Requêtes exécutées » listant, pour chaque requête SQL qui a produit ces chiffres, son texte exact tel qu'envoyé, le nombre de lignes renvoyées et les valeurs utilisées (un extrait si le résultat est long). Ne montrer que des requêtes réellement exécutées et leurs résultats réels, sans les reformuler; résumer en une ligne les requêtes de découverte (fiches, droits, colonnes).

## Règles de graphiques — topic=graphs

**Bibliothèques :** Règles de graphiques NeoLab. Utiliser Python : pandas pour manipuler les résultats SQL, Matplotlib pour les figures scientifiques statiques; seaborn facultatif pour les distributions. Cartopy avec Matplotlib pour les cartes statiques et projections; Folium pour les cartes interactives exportées en HTML. GeoPandas/Shapely/pyproj seulement si des opérations de géométrie ou de reprojection sont nécessaires. cmocean pour les palettes de variables océanographiques, avec barre de couleur et unités explicites; conserver cividis en repli. Pour l’analyse physique océanographique : oceans fournit des utilitaires, gsw (GSW/TEOS-10) les propriétés thermodynamiques; xarray convient aux données multidimensionnelles/NetCDF. Ces bibliothèques sont facultatives selon le besoin; ne pas les installer ni les appeler toutes systématiquement. Vérifier pour chaque fonction les entrées requises, unités, convention scientifique et domaine de validité; toute grandeur dérivée conserve formule et provenance. Avec gsw, distinguer salinité pratique/absolue et température in situ/conservative; ne pas substituer directement pression et profondeur. Clarifier les hypothèses manquantes avant calcul. Plotly uniquement si une interaction est demandée ou utile à une exploration explicitée; fournir alors un HTML autonome. Vérifier les bibliothèques installées avant exécution; leur mention ici ne signifie pas qu’elles sont disponibles. Respecter un choix explicite de l’utilisateur.

**Données et calcul :** Le graphique représente le grain documenté et un résultat réellement calculé. Agréger dans SQL avant transfert. DbHub limite les réponses à 1 000 lignes : contrôler le nombre attendu et toute indication de résultat tronqué; ne jamais tracer un sous-ensemble tronqué comme une population complète. Une base vide produit un constat d’absence de données, aucun graphique avec données inventées. NULL et zéro restent distincts. Ne pas interpoler, lisser, normaliser ou exclure des valeurs sans méthode explicite; demander une clarification si cela change le sens scientifique.

**Style :** Style par défaut : fond blanc, police DejaVu Sans 11 pt, titre descriptif court en français, axes avec noms et unités vérifiées, légende lisible, grille fine gris clair et marges sans texte coupé. Couleurs catégorielles adaptées au daltonisme, palette séquentielle cividis pour une quantité continue. Conserver couleurs et échelles cohérentes entre panneaux comparables. Pas de 3D décorative ou double axe sans justification. Profils : profondeur en ordonnée croissante vers le bas; échelle logarithmique uniquement explicitée et compatible avec zéros/valeurs négatives. Conserver les deux dénominateurs FILET séparés et appliquer l’agrégation UVP pondérée par volume. Filet–UVP (explore.filet_uvp_compare, document filet-uvp-comparaison) : une carte de couples place un point par déploiement filet (filet_deployment_id) relié à son profil UVP; la réponse donne le nombre de déploiements, de profils UVP et de stations, pas de lignes. Ne pas opposer le total des copépodes du filet à l’UVP comme une même grandeur : l’UVP ne voit que les gros individus; comparer taille contre taille (stades détaillés, carbone par individu p_min_filet_ug_c_per_ind, taille UVP min_size_um) et le dire dans la réponse. Nuage filet contre UVP : axes en ind./m³ de même échelle, ligne 1:1 en tirets, couples étiquetés par station; nombre d’objets UVP et couverture de la couche (uvp_layer_coverage) dans la réponse (tableau), couverture < 0,95 signalée. Profil vertical : couches du filet en barres horizontales de min_sample_depth à max_sample_depth, UVP au même grain de couche (ou par tranche, en le disant). Cartographie : vérifier le CRS; les coordonnées du warehouse sont en degrés WGS84. Avec Cartopy, séparer projection d’affichage et transform des données : PlateCarree pour les longitudes/latitudes WGS84, projection polaire adaptée à l’Arctique si pertinente. Ordre des points : Cartopy (longitude, latitude), Folium [latitude, longitude], GeoJSON [longitude, latitude]. Exclure explicitement les coordonnées manquantes/hors domaine sans les inventer. Calculer les distances en géodésique/PostGIS, pas en degrés ni en pixels. Conserver la version des zones et les ambiguïtés; distinguer source, statut et concentration dans la légende. Identifier les fonds/tuiles et leurs attributions. Les tuiles, bibliothèques JavaScript distantes et fonds Cartopy peuvent nécessiter Internet ou un cache local : ne pas annoncer une carte Folium autonome hors ligne sans l’avoir vérifiée. Privilégier les fonds locaux/caches; confirmer tout téléchargement lourd.

**Statut et livraison :** La figure reste sobre : titre court, axes avec unités, légende; aucun cartouche de statut, aucune note de source, de paramètres, de comptes ou de limites dans l’image (ils surchargent le graphique). Ces informations vont dans la RÉPONSE de l’agent, à côté de la figure : statut Exploratoire par défaut (pas une probabilité de confiance), source et requête, paramètres, comptes, exclusions et limites. Statuts : confirmed exige une validation scientifique explicitement documentée (un match accepted ou un test technique réussi ne suffit pas); exploratory par défaut; uncertain signale les limites connues, sans inventer de valeurs ou d’intervalles. Si une même figure mêle des séries de statuts différents, les distinguer par le trait (confirmed #007B88 plein, exploratory #B87514 tirets, uncertain #737C86 pointillés) avec un libellé dans la légende, jamais la couleur seule. Aucune interprétation biologique, aucun ajustement statistique ni intervalle d’incertitude inventé. Conserver requête SQL, paramètres, versions, méthode, exclusions et limites dans un fichier de provenance accompagnant la figure. Produire un PNG à 300 dpi et un SVG pour les figures statiques, le CSV exact tracé et le script Python reproductible; indiquer les chemins réels des fichiers créés. Fichiers : les écrire dans le dossier de travail courant avec des chemins relatifs (jamais un chemin absolu recopié à la main), puis vérifier qu’ils existent (ex. ls) et donner le chemin absolu réellement affiché par cette vérification. Rendu : relire l’image finale APRÈS la dernière modification du script, pas une version antérieure; si une retouche suit la relecture, relire de nouveau. Abondance « totale » ou « tous taxons » : exclure les catégories non vivantes et techniques (object_class de explore.ecotaxa_taxa), ou nommer la grandeur concentration de particules (objets/m³), jamais individus/m³; donner la part de détritus. Abondance par taxon : tracer la politique validated_only à côté de all_loaded_objects (ou expliquer pourquoi une seule), avec le nombre de profils de chacune, car all_loaded_objects inclut les objets prédits non validés. Signaler toute limite restante.

## explore.ecotaxa_projects

Inventaire de TOUS les projets EcoTaxa chargés, quel que soit l’instrument (UVP, Zooscan, LOKI…), avec leurs objets par statut d’annotation.

**Grain :** Un projet EcoTaxa par ligne.

**Relations :** ecotaxa_project_id vers ecotaxa_samples, ecotaxa_objects, uvp_projects, uvp_samples. has_uvp_profiles dit si des profils UVP (donc des volumes) existent.

**Limites :** Point d’entrée pour toute question sur « les projets » ou « les objets EcoTaxa » en général : uvp_projects ne couvre que les projets liés à un profil UVP. Les compteurs sont la somme des compteurs des samples (recalculés depuis les objets chargés). Dire dans la réponse quel périmètre est couvert (tous les projets, ou seulement ceux liés à l’UVP). Des projets peuvent être des copies les uns des autres (149 contient les 199 samples de 20880 + 20890, mêmes comptes, plus 5 samples propres, et 13224 est un extrait de 149 : 149 seul donne GreenEdge 2016 sans doublon) : voir la fiche ecotaxa_samples avant d’additionner.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| ecotaxa_project_title | text | Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id. |
| instrument | text | Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet. |
| ecotaxa_status | text | Statut du projet dans EcoTaxa (ex. Annotate), tel que fourni. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| n_samples | bigint | Nombre d’échantillons FILET du déploiement (un par filet et couche, ou filets regroupés). |
| n_objects | numeric | Nombre d’objets chargés du projet (somme de object_count des samples). |
| n_validated | numeric | Objets validés (annotation_status = validated) du projet, somme des samples. |
| n_predicted | numeric | Objets prédits automatiquement, non validés (annotation_status = predicted), somme des samples. |
| n_dubious | numeric | Objets marqués douteux (annotation_status = dubious), somme des samples. |
| n_unclassified | numeric | Objets jamais classés (sans statut ni catégorie), somme des samples. |
| start_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| end_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| marine_zone_keys | ARRAY | Toutes les zones attribuées aux profils/samples du projet (tableau, AMBIGUOUS compris); filtrer avec = ANY(marine_zone_keys). |
| has_uvp_profiles | boolean | Vrai si au moins un sample du projet est lié à un profil UVP (EcoPart), donc à des volumes échantillonnés. |

```sql
SELECT ecotaxa_project_id, ecotaxa_project_title, instrument, n_objects, n_validated, n_predicted FROM explore.ecotaxa_projects ORDER BY n_objects DESC;
```

## explore.ecotaxa_samples

Tous les samples EcoTaxa, tous projets et instruments, avec position, date, zone et compteurs d’objets par statut d’annotation.

**Grain :** Un sample EcoTaxa par ligne.

**Relations :** ecotaxa_sample_id vers ecotaxa_objects.ecotaxa_sample_id et uvp_samples.ecotaxa_sample_id; ecotaxa_project_id vers ecotaxa_projects.

**Limites :** Pour compter ou comparer des statuts d’annotation, partir d’ici (rapide) et non de ecotaxa_objects. uvp_samples ne montre que les samples liés à un profil UVP et peut répéter un sample lié à plusieurs profils; ici une ligne = un sample. Deux projets peuvent porter des copies des mêmes images (ex. 149 contient les 199 samples de 20880 + 20890, mêmes comptes, plus 5 samples propres; 13224 est un extrait de 10 000 objets des mêmes 204 samples que 149) : vérifier avant d’additionner des projets. Une copie a toujours d’autres identifiants d’objet, et un titre proche ne prouve rien : comparer les comptes par profil UVP ou par sample; sans cette comparaison, écrire « copie possible, non vérifiée » plutôt que l’affirmer. Pas de volume échantillonné : pas d’abondance ici.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| ecotaxa_project_title | text | Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id. |
| instrument | text | Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecotaxa_native_sample_id | text | Identifiant natif du sample EcoTaxa; qualifier par projet/version. |
| sample_orig_id | text | Identifiant original du sample EcoTaxa, utilisé par les liens de provenance. |
| ecotaxa_station_id | text | Station fournie dans les métadonnées EcoTaxa. |
| ecotaxa_cruise_id | text | Campagne fournie dans les métadonnées EcoTaxa. |
| ecotaxa_profile_id | text | Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP. |
| datetime_min | timestamp with time zone | Date EcoTaxa du sample ou de l’objet. Les données chargées n’ont pas d’heure (toujours 00:00 UTC : l’heure EcoTaxa obj.objtime n’était pas demandée au chargement) : ne pas en déduire jour ou nuit. L’heure des profils UVP est dans uvp_samples.sampled_at (EcoPart). |
| datetime_max | timestamp with time zone | Date EcoTaxa du sample ou de l’objet. Les données chargées n’ont pas d’heure (toujours 00:00 UTC : l’heure EcoTaxa obj.objtime n’était pas demandée au chargement) : ne pas en déduire jour ou nuit. L’heure des profils UVP est dans uvp_samples.sampled_at (EcoPart). |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| depth_min | double precision | Borne de profondeur fournie dans les métadonnées EcoTaxa; unité à vérifier dans la source. |
| depth_max | double precision | Borne de profondeur fournie dans les métadonnées EcoTaxa; unité à vérifier dans la source. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| object_count | bigint | Nombre d’objets chargés de ce sample (recalculé depuis les objets chargés). |
| nb_validated | bigint | Nombre d’objets chargés de ce sample avec annotation_status = validated (recalculé depuis les objets). |
| nb_predicted | bigint | Nombre d’objets chargés de ce sample avec annotation_status = predicted (recalculé depuis les objets). |
| nb_dubious | bigint | Nombre d’objets chargés de ce sample avec annotation_status = dubious (recalculé depuis les objets). |
| nb_unclassified | bigint | Nombre d’objets chargés de ce sample sans statut (jamais classés), recalculé depuis les objets. |
| has_uvp_profile | boolean | Vrai si ce sample est lié à au moins un profil UVP (voir uvp_samples). |
| sampled_at | timestamp with time zone | Date EcoTaxa du sample ou de l’objet. Les données chargées n’ont pas d’heure (toujours 00:00 UTC : l’heure EcoTaxa obj.objtime n’était pas demandée au chargement) : ne pas en déduire jour ou nuit. L’heure des profils UVP est dans uvp_samples.sampled_at (EcoPart). |

```sql
SELECT ecotaxa_project_id, SUM(nb_validated) AS valides, SUM(nb_predicted) AS predits FROM explore.ecotaxa_samples GROUP BY 1;
```

## explore.ecotaxa_objects

Tous les objets EcoTaxa (15 M), tous projets et instruments : taxon, statut d’annotation, profondeur, taille.

**Grain :** Un objet EcoTaxa par ligne.

**Relations :** ecotaxa_sample_id vers ecotaxa_samples; ecotaxa_project_id vers ecotaxa_projects; ecotaxa_object_id = uvp_objects.ecotaxa_object_id pour les objets liés à un profil UVP.

**Limites :** Toujours filtrer par ecotaxa_project_id ou ecotaxa_sample_id et agréger dans la requête : un balayage complet dépasse le délai de 30 s. Pour de simples comptes par statut, ecotaxa_samples suffit; pour chercher un taxon ou compter par taxon, ecotaxa_sample_taxa (un filtre sur taxon_name ici, même avec le projet, peut dépasser 30 s). Ici, réserver ecotaxa_objects à la profondeur, à la taille et aux données propres à chaque objet. Depuis le 8 novembre 2026 : object_datetime porte l’heure EcoTaxa; sun_position est le code EcoTaxa de position du soleil (D jour, A aube, U crépuscule, N nuit, ? indéterminé; sens vérifié sur les données par l’élévation solaire; NULL pour environ 2 objets sur 3, que EcoTaxa ne calcule pas, ex. aucun code pour am_leg3 : toujours dire combien d’objets ont un code); annotator_id est un identifiant EcoTaxa sans nom, annotated_at la date de la dernière validation manuelle (pas la date de prélèvement); prediction_score n’existe que pour les objets prédits; image_uri est l’adresse publique directe de l’image (vérifiée, s’ouvre sans connexion); perim_px, feret_px (et perim_um, feret_um), circularity, elongation, mean_grey, convex_area_px sont les mesures ZooProcess, NULL pour tous les projets LOKI (qui ont leurs propres descripteurs, non chargés), pas une absence d’export. Tailles réelles (_um) NULL sans calibration pixel (LOKI notamment), jamais zéro. Pas d’abondance (ind/m³) sans volume : passer par les vues UVP.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_object_id | bigint | Clé technique de l’objet EcoTaxa; utiliser DISTINCT si une jointure peut multiplier ses lignes. |
| object_id | text | Identifiant natif de l’objet EcoTaxa, qualifié par son sample/source. |
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| instrument | text | Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet. |
| taxon_id | text | Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite. |
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| annotation_status | text | Statut d’annotation EcoTaxa (classif_qual) : validated (V, validé par un humain), predicted (P, classification automatique), dubious (D); NULL = objet jamais classé (ou chargé avant l’ajout du statut), pas validated. |
| object_datetime | timestamp with time zone | Date et heure de l’objet fournies par EcoTaxa; peut être NULL. |
| object_depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| object_depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| object_lat | double precision | Latitude de l’objet fournie par EcoTaxa (WGS84); souvent celle du sample ou NULL. |
| object_lon | double precision | Longitude de l’objet fournie par EcoTaxa (WGS84); souvent celle du sample ou NULL. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| acquisition_id | text | Identifiant natif d’acquisition EcoTaxa. |
| area_px | double precision | Aire Zooprocess de l’objet EcoTaxa, en pixels; valeur source, non recalculée. |
| esd_px | double precision | Diamètre sphérique équivalent Zooprocess, en pixels; NULL si le projet EcoTaxa ne fournit pas cette colonne libre. |
| major_px | double precision | Axe majeur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée. |
| minor_px | double precision | Axe mineur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée. |
| pixel_size_mm | double precision | Taille réelle d’un pixel pour l’acquisition de l’objet, en mm (EcoTaxa la donne en mm pour UVP5/Zooscan et en µm pour UVP6 : convertie ici; ordre de grandeur 0,07 à 0,17 mm); NULL si EcoTaxa ne la fournit pas (LOKI, Zooscan), auquel cas aucune colonne _um/_um2 n’est calculable pour cet objet. |
| esd_um | double precision | esd_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| major_um | double precision | major_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| minor_um | double precision | minor_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| area_um2 | double precision | area_px convertie en micromètres carrés via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une aire nulle. |
| taxon_lineage | ARRAY | Lignée EcoTaxa de la catégorie, du taxon lui-même jusqu’à la racine (ex. Calanoida, Gymnoplea, Neocopepoda, Copepoda, …, Biota) : un groupe se filtre par 'Copepoda' = ANY(taxon_lineage). Inclut les catégories morphologiques (stades, vues, mais aussi part, dead, eggs, like) : dire lesquelles sont gardées. NULL si la taxonomie n’est pas chargée. |
| taxon_type | text | Type de catégorie EcoTaxa : P (phylogénétique, un taxon) ou M (morphologique : stade, vue, taille, mais aussi part, cut, dead, eggs, like...). M ne veut pas dire fragment. |
| object_class | text | Nature des objets de la catégorie, d’après la racine de sa lignée EcoTaxa : organism (sous Biota), not_living (détritus, artefacts, fèces), technical (Biota : badsegmentation, oversegmented, duplicate), temporary (catégories provisoires t0xx), unknown. Un total d’organismes exige organism; NULL si la taxonomie n’est pas chargée. |
| sun_position | text | Position du soleil calculée par EcoTaxa pour l’objet (obj.sunpos) : D jour, A aube, U crépuscule, N nuit, ? indéterminé; NULL si EcoTaxa ne l’a pas calculée (environ 2 objets sur 3). Sens vérifié sur les données (élévation moyenne +20° pour D, -21° pour N, -7° le matin pour A, -8° le soir pour U). Pour jour/nuit, dire combien d’objets ont un code. |
| annotator_id | integer | Identifiant EcoTaxa de la personne qui a classé l’objet à la main (obj.classif_who), sans nom; NULL pour un objet jamais validé à la main ou pas encore rechargé. |
| annotated_at | timestamp with time zone | Date de la dernière classification manuelle dans EcoTaxa (obj.classif_when); NULL si jamais validé à la main ou pas encore rechargé. |
| prediction_score | double precision | Score de la prédiction automatique EcoTaxa (obj.classif_auto_score, entre 0 et 1); souvent NULL pour un objet validé; ne dit rien de la justesse d’une validation humaine. |
| image_uri | text | Référence d’image source de l’objet; sa présence ne garantit pas l’accessibilité de l’image. |
| perim_px | double precision | Périmètre ZooProcess de l’objet, en pixels (free column « perim. »); NULL si le projet ne le fournit pas (LOKI) ou pas encore rechargé. |
| feret_px | double precision | Diamètre de Feret maximal ZooProcess, en pixels (free column « feret »). |
| circularity | double precision | Circularité ZooProcess (free column « circ. »), sans unité, 1 pour un disque. |
| elongation | double precision | Élongation ZooProcess (free column « elongation »), sans unité. |
| mean_grey | double precision | Niveau de gris moyen de l’objet (free column « mean »), dans l’échelle de l’image source : ne pas comparer entre instruments. |
| convex_area_px | double precision | Aire de l’enveloppe convexe ZooProcess, en pixels (free column « convarea »). |
| perim_um | double precision | Périmètre en micromètres : perim_px × pixel_size_mm × 1000; NULL sans calibration pixel. |
| feret_um | double precision | Diamètre de Feret en micromètres : feret_px × pixel_size_mm × 1000; NULL sans calibration pixel. |

```sql
SELECT taxon_name, annotation_status, COUNT(*) FROM explore.ecotaxa_objects WHERE ecotaxa_project_id = 12063 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
```

## explore.ecotaxa_sample_taxa

Nombre d’objets par sample EcoTaxa et par catégorie (taxon), par statut d’annotation, avec la lignée du taxon : la vue pour chercher un taxon, savoir dans quels projets ou samples il est, et compter par taxon.

**Grain :** Un sample EcoTaxa × une catégorie par ligne (environ 40 000 lignes); taxon_id NULL = objets jamais classés.

**Relations :** ecotaxa_sample_id vers ecotaxa_samples et ecotaxa_objects; ecotaxa_project_id vers ecotaxa_projects; taxon_id vers ecotaxa_taxa et ecotaxa_objects.taxon_id.

**Limites :** Rapide (moins d’une seconde) : chercher ici un taxon par nom (taxon_name ILIKE), jamais dans ecotaxa_objects. Un groupe (« les copépodes ») se lit dans la lignée EcoTaxa : 'Copepoda' = ANY(taxon_lineage), jamais d’une liste de genres dressée de mémoire. Cette lignée inclut les organismes entiers (taxons, stades et vues comme female+lateral<Metridia longa, small<, ovigerous) mais aussi des catégories qui ne sont pas un copépode entier vivant (part<, cut<, antenna<, copepoda eggs, dead<) ou incertaines (like<, badfocus<, multiple<) : dire lesquelles sont gardées et donner le total avec et sans elles. taxon_type M (morphologique) ne veut pas dire fragment : les stades et vues sont M. Mêmes précautions sur les doublons de projets que ecotaxa_samples (149, 20880, 20890, 13224). object_class sépare organismes, non vivants (détritus...), catégories techniques et provisoires : un total d’organismes exige object_class = 'organism'. Pas de profondeur, de taille ni de volume ici.

| Colonne | Type SQL | Définition |
|---|---|---|
| ecotaxa_sample_id | bigint | Clé technique du sample EcoTaxa; distincte de son identifiant natif. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| ecotaxa_project_title | text | Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id. |
| instrument | text | Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet. |
| ecotaxa_native_sample_id | text | Identifiant natif du sample EcoTaxa; qualifier par projet/version. |
| sampled_at | timestamp with time zone | Date EcoTaxa du sample ou de l’objet. Les données chargées n’ont pas d’heure (toujours 00:00 UTC : l’heure EcoTaxa obj.objtime n’était pas demandée au chargement) : ne pas en déduire jour ou nuit. L’heure des profils UVP est dans uvp_samples.sampled_at (EcoPart). |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| taxon_id | integer | Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite. |
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| taxon_type | text | Type de catégorie EcoTaxa : P (phylogénétique, un taxon) ou M (morphologique : stade, vue, taille, mais aussi part, cut, dead, eggs, like...). M ne veut pas dire fragment. |
| taxon_lineage | ARRAY | Lignée EcoTaxa de la catégorie, du taxon lui-même jusqu’à la racine (ex. Calanoida, Gymnoplea, Neocopepoda, Copepoda, …, Biota) : un groupe se filtre par 'Copepoda' = ANY(taxon_lineage). Inclut les catégories morphologiques (stades, vues, mais aussi part, dead, eggs, like) : dire lesquelles sont gardées. NULL si la taxonomie n’est pas chargée. |
| n_objects | bigint | Nombre d’objets de ce sample dans cette catégorie. |
| n_validated | bigint | Objets validés (annotation_status = validated) de ce sample dans cette catégorie. |
| n_predicted | bigint | Objets prédits automatiquement, non validés, de ce sample dans cette catégorie. |
| n_dubious | bigint | Objets marqués douteux de ce sample dans cette catégorie. |
| n_unclassified | bigint | Objets jamais classés de ce sample dans cette catégorie. |
| object_class | text | Nature des objets de la catégorie, d’après la racine de sa lignée EcoTaxa : organism (sous Biota), not_living (détritus, artefacts, fèces), technical (Biota : badsegmentation, oversegmented, duplicate), temporary (catégories provisoires t0xx), unknown. Un total d’organismes exige organism; NULL si la taxonomie n’est pas chargée. |

```sql
SELECT ecotaxa_project_id, taxon_name, SUM(n_validated) AS valides, SUM(n_objects) AS objets FROM explore.ecotaxa_sample_taxa WHERE 'Copepoda' = ANY(taxon_lineage) AND ecotaxa_project_id = 14859 GROUP BY 1,2 ORDER BY 4 DESC;
```

## explore.ecotaxa_taxa

Les catégories EcoTaxa présentes dans le warehouse, avec leur lignée jusqu’à la racine (taxonomie EcoTaxa), leur type, leur rang, leur AphiaID WoRMS et leurs totaux.

**Grain :** Une catégorie EcoTaxa par ligne (340).

**Relations :** taxon_id vers ecotaxa_sample_taxa.taxon_id et ecotaxa_objects.taxon_id; taxon_name identique au taxon_name des objets.

**Limites :** object_class : organism (sous Biota), not_living (détritus, artefacts, fèces), technical (badsegmentation, oversegmented, duplicate), temporary (t0xx); taxon_key se joint à uvp_taxon_abundance.taxon_key. Pour savoir quelles catégories appartiennent à un groupe : WHERE 'Copepoda' = ANY(taxon_lineage); taxon_short_name donne le qualificatif d’une catégorie morphologique (part, cut, dead, like...). Les totaux ne couvrent que ce que le compte peut lire. La lignée est celle d’EcoTaxa au moment du chargement (fetched_at dans la source), pas une révision taxonomique.

| Colonne | Type SQL | Définition |
|---|---|---|
| taxon_id | integer | Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite. |
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| taxon_short_name | text | Nom court EcoTaxa de la catégorie (pour une catégorie morphologique, son qualificatif : part, cut, dead, like, female+lateral...). |
| taxon_type | text | Type de catégorie EcoTaxa : P (phylogénétique, un taxon) ou M (morphologique : stade, vue, taille, mais aussi part, cut, dead, eggs, like...). M ne veut pas dire fragment. |
| taxon_rank | text | Rang taxonomique EcoTaxa (Class, Order, Genus...), NULL pour les catégories morphologiques. |
| taxon_lineage | ARRAY | Lignée EcoTaxa de la catégorie, du taxon lui-même jusqu’à la racine (ex. Calanoida, Gymnoplea, Neocopepoda, Copepoda, …, Biota) : un groupe se filtre par 'Copepoda' = ANY(taxon_lineage). Inclut les catégories morphologiques (stades, vues, mais aussi part, dead, eggs, like) : dire lesquelles sont gardées. NULL si la taxonomie n’est pas chargée. |
| taxon_id_lineage | ARRAY | Identifiants EcoTaxa de la lignée, dans le même ordre que taxon_lineage. |
| aphia_id | integer | AphiaID WoRMS fourni par EcoTaxa, NULL si absent; pas une équivalence FILET implicite. |
| n_projects | bigint | Nombre de projets EcoTaxa où la catégorie a au moins un objet lisible par le compte. |
| n_samples | bigint | Nombre de samples EcoTaxa où la catégorie a au moins un objet lisible par le compte. |
| n_objects | numeric | Nombre d’objets de cette catégorie, tous projets lisibles. |
| n_validated | numeric | Objets validés (annotation_status = validated) de cette catégorie, tous projets lisibles. |
| n_predicted | numeric | Objets prédits automatiquement, non validés, de cette catégorie, tous projets lisibles. |
| n_dubious | numeric | Objets marqués douteux de cette catégorie, tous projets lisibles. |
| taxon_key | text | Clé dérivée : ecotaxa:id:…, ecotaxa:name:… ou warehouse:unclassified; ne pas présenter un libellé ou marqueur comme identifiant taxonomique officiel. |
| object_class | text | Nature des objets de la catégorie, d’après la racine de sa lignée EcoTaxa : organism (sous Biota), not_living (détritus, artefacts, fèces), technical (Biota : badsegmentation, oversegmented, duplicate), temporary (catégories provisoires t0xx), unknown. Un total d’organismes exige organism; NULL si la taxonomie n’est pas chargée. |

```sql
SELECT taxon_name, taxon_type, taxon_rank, n_projects, n_objects, n_validated FROM explore.ecotaxa_taxa WHERE 'Copepoda' = ANY(taxon_lineage) ORDER BY n_objects DESC NULLS LAST;
```

## explore.ctd_profiles

Tous les profils CTD Amundsen chargés, liés ou non à EcoTaxa.

**Grain :** Un profil CTD par ligne.

**Relations :** ctd_profile_id vers ctd_measurements; zone_membership (row_kind = ctd_profile, row_id = ctd_profile_id).

**Limites :** ecotaxa_ctd_profile ne montre que les profils liés à un sample EcoTaxa (une ligne par liaison); ici chaque profil une fois. max_depth_m est la profondeur maximale mesurée.

| Colonne | Type SQL | Définition |
|---|---|---|
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| source_profile_key | text | Identifiant natif du profil CTD. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| sampled_at | timestamp with time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| max_depth_m | double precision | Profondeur maximale mesurée dans ce profil CTD, en mètres. |
| has_ecotaxa_link | boolean | Vrai si le profil CTD a au moins une liaison acceptée avec un sample EcoTaxa. |

```sql
SELECT cruise_key, COUNT(*), MIN(sampled_at), MAX(sampled_at) FROM explore.ctd_profiles GROUP BY 1;
```

## explore.ctd_measurements

Mesures CTD (température, salinité, sigma-t, oxygène, nitrate, fluorescence, pression) de tous les profils, format long; pas de pH dans les données chargées.

**Grain :** Profil CTD × scan × variable.

**Relations :** ctd_profile_id vers ctd_profiles pour position, date et zone.

**Limites :** Filtrer variable_key et ctd_profile_id avant d’agréger (5 M lignes). Unité dans unit telle que fournie; ne convertir pression/profondeur ni salinité sans le dire. SIGT est le sigma-t (densité moins 1000 kg/m³) : 27 signifie 1027 kg/m³. depth_m est la pression en dbar prise pour des mètres (écart ≈ 1 % à 2000 m). qc est toujours NULL : aucun contrôle qualité fourni, à signaler. Pour un profil moyen, moyenner d’abord par profil et classe de profondeur, puis entre profils.

| Colonne | Type SQL | Définition |
|---|---|---|
| ctd_profile_id | bigint | Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles. |
| depth_m | double precision | Pression en dbar utilisée comme profondeur en mètres (1 dbar ≈ 0,99 m; écart d’environ 1 % à 2000 m), telle que fournie par le chargeur CTD; pas une profondeur recalculée (TEOS-10). |
| pressure_dbar | double precision | Pression CTD en dbar; ne pas assimiler automatiquement à la profondeur en mètres. |
| variable_key | text | Code de variable CTD; conserver les codes source et ne pas assimiler des variables sans vérifier définition/unité. |
| variable_name | text | Nom lisible de la variable CTD (référentiel ctd_variable), ex. température, salinité. |
| value | double precision | Valeur CTD fournie; interpréter avec unit, variable_key, sensor_channel et qc. |
| unit | text | Unité CTD fournie; aucune conversion implicite entre codes/sources. |
| qc | text | Indicateur qualité source CTD; NULL signifie absent, pas bon. |
| sensor_channel | text | Canal/capteur source CTD; deux canaux ne sont pas des répétitions à moyenner implicitement. |

```sql
SELECT ctd_profile_id, depth_m, value AS temperature FROM explore.ctd_measurements WHERE variable_key = 'TE90' AND ctd_profile_id = 1 ORDER BY depth_m;
```

## explore.uvp_projects

Inventaire agrégé des projets UVP liés à EcoTaxa/EcoPart.

**Grain :** Projet EcoTaxa × projet EcoPart × campagne; EcoTaxa peut être NULL.

**Relations :** Navigation vers uvp_samples par ecotaxa_project_id et ecopart_project_id; sélectionner la campagne.

**Limites :** Ne pas sommer des projets qui réutilisent les mêmes profils. marine_zone_key/name (MIN) ne montrent qu’UNE zone : pour savoir si un projet touche une zone, filtrer sur marine_zone_keys (toutes les zones attribuées à ses profils/samples), ex. WHERE 'Baie de Baffin' = ANY(marine_zone_keys); les points en chevauchement de zones (AMBIGUOUS) se retrouvent par explore.zone_membership. Pas de dataset_version_id dans cette vue : auditer les versions dans dataset_versions et les vues détaillées. ecotaxa_project_title est le nom natif du projet EcoTaxa, pour affichage (légende, étiquette) : NULL si le projet n’a pas été chargé dans warehouse.ecotaxa_project, et ne pas l’utiliser comme clé (deux projets pourraient en théorie partager un titre) — grouper/joindre sur ecotaxa_project_id.

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
| ecotaxa_project_title | text | Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id. |
| marine_zone_keys | ARRAY | Toutes les zones attribuées aux profils/samples du projet (tableau, AMBIGUOUS compris); filtrer avec = ANY(marine_zone_keys). |

```sql
SELECT * FROM explore.uvp_projects LIMIT 20;
```

## explore.uvp_samples

Métadonnées des profils UVP liés à un sample EcoTaxa.

**Grain :** Profil UVP × liaison sample EcoTaxa; plusieurs liaisons par profil possibles.

**Relations :** uvp_profile_id = uvp_taxon_abundance.profile_id ou ecopart_bins.profile_id; ecotaxa_sample_id = ecotaxa_ctd_profile.ecotaxa_sample_id.

**Limites :** INNER JOIN : les profils sans sample EcoTaxa lié sont absents. COUNT(DISTINCT uvp_profile_id) pour compter les profils. marine_zone_key est ici la zone du sample EcoTaxa lié (sinon celle du profil) : un profil dont les samples se contredisent (profils GreenEdge 2016 vers 70° N : Baie de Baffin dans 149, Détroit de Davis dans 20890) apparaît dans les deux zones, et son profil est AMBIGUOUS (absent de zone_membership s’il n’a pas de coordonnées propres). Dire quel filtre de zone est utilisé quand le compte diffère de zone_membership. ecotaxa_project_title est le nom natif du projet, pour affichage uniquement (peut être NULL); ecotaxa_project_id reste la clé stable.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| ecopart_sample_id | text | Identifiant natif du sample EcoPart, si fourni. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| cast_key | text | Identifiant/libellé de cast du profil UVP. |
| sampled_at | timestamp with time zone | Heure de capture du profil UVP donnée par EcoPart (métadonnées « yyyy-mm-dd hh:mm »), lue en UTC, convention du warehouse pour une heure source sans fuseau. Utilisable pour jour/nuit, en le disant. |
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
| object_count | bigint | Nombre d’objets chargés de ce sample (recalculé depuis les objets chargés). |
| nb_validated | bigint | Nombre d’objets chargés de ce sample avec annotation_status = validated (recalculé depuis les objets). |
| nb_predicted | bigint | Nombre d’objets chargés de ce sample avec annotation_status = predicted (recalculé depuis les objets). |
| nb_dubious | bigint | Nombre d’objets chargés de ce sample avec annotation_status = dubious (recalculé depuis les objets). |
| nb_unclassified | bigint | Nombre d’objets chargés de ce sample sans statut (jamais classés), recalculé depuis les objets. |
| ecotaxa_project_title | text | Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id. |

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
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| sampled_at | timestamp with time zone | Heure de capture du profil UVP donnée par EcoPart (métadonnées « yyyy-mm-dd hh:mm »), lue en UTC, convention du warehouse pour une heure source sans fuseau. Utilisable pour jour/nuit, en le disant. |
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
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| annotation_status | text | Statut d’annotation EcoTaxa (classif_qual) : validated (V, validé par un humain), predicted (P, classification automatique), dubious (D); NULL = objet jamais classé (ou chargé avant l’ajout du statut), pas validated. |
| object_depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| object_depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| uvp_bin_id | bigint | Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin. |
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
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| ecopart_project_id | bigint | Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa. |
| profile_id | bigint | Ancien nom de la clé du profil UVP dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_profile_id (présente aussi dans ces vues), à privilégier. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| bin_id | bigint | Ancien nom de la clé du bin EcoPart dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_bin_id, à privilégier. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| source_depth_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| source_row_json | jsonb | Ligne source complète conservée en JSON; noms et unités non harmonisés. Inspecter avant calcul. |
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| uvp_bin_id | bigint | Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin. |

```sql
SELECT profile_id,bin_id,depth_min_m,depth_max_m,sampled_volume_l FROM explore.ecopart_bins LIMIT 20;
```

## explore.uvp_taxon_abundance

Abondances UVP dérivées des objets EcoTaxa et volumes EcoPart.

**Grain :** Version dérivée × profil × bin × taxon_key × annotation_policy.

**Relations :** profile_id vers uvp_samples.uvp_profile_id; bin_id vers ecopart_bins.bin_id. Isoler annotation_policy et dataset_version_id. ecotaxa_project_id vers uvp_projects.ecotaxa_project_id.

**Limites :** Formule : n_objects_taxon / sampled_volume_l × 1000, individus/m³. Agréger par SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000, pas par moyenne simple. Filtre de zone complet (y compris points AMBIGUOUS) : JOIN explore.zone_membership m ON m.row_kind='uvp_profile' AND m.row_id=profile_id. La vue ajoute des zéros sur tous les bins uniquement pour les taxons observés dans ce profil et cette annotation_policy; un taxon absent du profil entier ne reçoit pas de zéro. Pour un profil présent, chaque bin a donc ses lignes, zéros compris : aucun bin ne manque au volume d’un total par tranche. Total « tous taxons » : la vue contient aussi les catégories non vivantes (détritus, artefacts, fèces : 99 % des objets validés du projet 10101 en Baie de Baffin, dont 97 % de détritus) et techniques; une abondance d’organismes se calcule avec JOIN explore.ecotaxa_taxa t ON t.taxon_key = a.taxon_key WHERE t.object_class = 'organism', sinon c’est une concentration de particules (objets/m³, pas individus/m³), à nommer ainsi; toujours dire la composition retenue. annotation_policy vaut all_loaded_objects:ecotaxa_project=N (tous les objets chargés : validés, prédits, douteux et jamais classés) ou validated_only:ecotaxa_project=N (validés seulement, statut V d’EcoTaxa) : toujours filtrer une seule politique et la nommer dans la réponse; comparer les deux pour montrer la part du prédit. Attention avec validated_only : un profil sans aucun objet validé de ce taxon n’a pas de ligne (pas de zéro, l’annotation y est peut-être incomplète), donc le volume de référence diffère de all_loaded_objects; toujours donner, pour chaque politique, le nombre de profils et le volume total utilisés, et ne pas présenter l’écart entre politiques comme une différence biologique. Ne pas sommer le même volume sur plusieurs taxons. marine_zone_key/name/assignment_status viennent directement de uvp_profile : disponibles même quand explore.uvp_samples est vide pour ce profil (pas de sample EcoTaxa lié) — ne pas passer par uvp_samples pour la zone, elle est déjà ici.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| profile_id | bigint | Ancien nom de la clé du profil UVP dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_profile_id (présente aussi dans ces vues), à privilégier. |
| bin_id | bigint | Ancien nom de la clé du bin EcoPart dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_bin_id, à privilégier. |
| taxon_key | text | Clé dérivée : ecotaxa:id:…, ecotaxa:name:… ou warehouse:unclassified; ne pas présenter un libellé ou marqueur comme identifiant taxonomique officiel. |
| annotation_policy | text | Politique de sélection des objets et projet EcoTaxa : all_loaded_objects:ecotaxa_project=N (tous les objets chargés, validés ou non) ou validated_only:ecotaxa_project=N (annotation_status = validated seulement). Filtrer une seule politique. |
| n_objects_taxon | bigint | Nombre d’objets du taxon pour le bin et la politique; zéros densifiés selon le contrat de la vue. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| abundance_uvp_ind_m3 | numeric | Abondance UVP dérivée en individus/m³ : n_objects_taxon / sampled_volume_l × 1000. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| cruise_key | text | Libellé/clé de campagne de la source; pas de normalisation inter-source implicite. |
| station_key | text | Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source. |
| sampled_at | timestamp with time zone | Heure de capture du profil UVP donnée par EcoPart (métadonnées « yyyy-mm-dd hh:mm »), lue en UTC, convention du warehouse pour une heure source sans fuseau. Utilisable pour jour/nuit, en le disant. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| ecotaxa_project_id | bigint | Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart. |
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| uvp_bin_id | bigint | Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin. |

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
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| sampled_at | timestamp with time zone | Heure de capture du profil UVP donnée par EcoPart (métadonnées « yyyy-mm-dd hh:mm »), lue en UTC, convention du warehouse pour une heure source sans fuseau. Utilisable pour jour/nuit, en le disant. |
| uvp_bin_id | bigint | Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin. |
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

## explore.uvp_object_sizes

Un objet EcoTaxa identifié (taxon) par ligne, avec sa taille réelle quand elle est calculable.

**Grain :** Objet EcoTaxa (un par ligne), avec le bin EcoPart auquel il est rattaché.

**Relations :** uvp_profile_id vers uvp_samples.uvp_profile_id; uvp_bin_id vers le bin de profondeur; taxon_id/taxon_name comme sur explore.uvp_objects. Distinct de uvp_taxon_abundance (agrégée par bin/taxon, sans taille) et de uvp_particle_sizes (taille sans taxon) : ici, taxon et taille sont sur la même ligne. taxon_key suit la même convention que uvp_taxon_abundance.taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified) : pour comparer à une abondance FILET du même taxon, joindre explore.taxon_mapping sur uvp_taxon_id = taxon_key, comme explore.filet_uvp_abundance le fait en interne.

**Limites :** esd_um/major_um/minor_um/area_um2 sont NULL quand la calibration pixel de l’acquisition EcoTaxa (pixel_size_mm) est inconnue — ne pas traiter un NULL comme une taille nulle ni l’exclure silencieusement sans le signaler. esd_px/major_px/minor_px/area_px sont les valeurs source EcoTaxa (Zooprocess), non recalculées; _um/_um2 sont calculées ici. sampled_volume_l est un attribut du bin, répété sur chaque objet de ce bin : pour une densité par taxon et gamme de taille, agréger ce volume une seule fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id) avant de diviser, comme pour uvp_particle_sizes. Un objet peut ne pas être rattaché à un bin (uvp_bin_id NULL) : l’exclure explicitement d’un calcul de densité plutôt que de le laisser fausser silencieusement une moyenne.

| Colonne | Type SQL | Définition |
|---|---|---|
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| sample_name | text | Nom natif du profil EcoPart; pas un identifiant global. |
| marine_zone_key | text | Clé de zone maritime attribuée; consulter source, version et statut. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| sampled_at | timestamp with time zone | Heure de capture du profil UVP donnée par EcoPart (métadonnées « yyyy-mm-dd hh:mm »), lue en UTC, convention du warehouse pour une heure source sans fuseau. Utilisable pour jour/nuit, en le disant. |
| ecotaxa_object_id | bigint | Clé technique de l’objet EcoTaxa; utiliser DISTINCT si une jointure peut multiplier ses lignes. |
| object_id | text | Identifiant natif de l’objet EcoTaxa, qualifié par son sample/source. |
| acquisition_id | text | Identifiant natif d’acquisition EcoTaxa. |
| taxon_id | text | Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite. |
| taxon_name | text | Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation. |
| annotation_status | text | Statut d’annotation EcoTaxa (classif_qual) : validated (V, validé par un humain), predicted (P, classification automatique), dubious (D); NULL = objet jamais classé (ou chargé avant l’ajout du statut), pas validated. |
| taxon_key | text | Clé dérivée : ecotaxa:id:…, ecotaxa:name:… ou warehouse:unclassified; ne pas présenter un libellé ou marqueur comme identifiant taxonomique officiel. |
| object_depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| object_depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| uvp_bin_id | bigint | Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin. |
| depth_min_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| depth_max_m | double precision | Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains. |
| sampled_volume_l | numeric | Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons. |
| area_px | double precision | Aire Zooprocess de l’objet EcoTaxa, en pixels; valeur source, non recalculée. |
| esd_px | double precision | Diamètre sphérique équivalent Zooprocess, en pixels; NULL si le projet EcoTaxa ne fournit pas cette colonne libre. |
| major_px | double precision | Axe majeur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée. |
| minor_px | double precision | Axe mineur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée. |
| pixel_size_mm | double precision | Taille réelle d’un pixel pour l’acquisition de l’objet, en mm (EcoTaxa la donne en mm pour UVP5/Zooscan et en µm pour UVP6 : convertie ici; ordre de grandeur 0,07 à 0,17 mm); NULL si EcoTaxa ne la fournit pas (LOKI, Zooscan), auquel cas aucune colonne _um/_um2 n’est calculable pour cet objet. |
| esd_um | double precision | esd_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| major_um | double precision | major_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| minor_um | double precision | minor_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle. |
| area_um2 | double precision | area_px convertie en micromètres carrés via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une aire nulle. |

```sql
WITH per_bin AS (SELECT uvp_bin_id, MIN(sampled_volume_l) AS vol_l, COUNT(*) AS n FROM explore.uvp_object_sizes WHERE taxon_name ILIKE '%calanus%' AND major_um BETWEEN 500 AND 1000 AND uvp_bin_id IS NOT NULL GROUP BY uvp_bin_id) SELECT SUM(n)/SUM(vol_l)*1000 AS ind_m3 FROM per_bin;
```

## explore.taxon_mapping

Correspondance taxonomique FILET↔UVP retenue (statut accepted uniquement).

**Grain :** Une ligne par paire filet_taxon_id/uvp_taxon_id/mapping_version retenue.

**Relations :** filet_taxon_id vers filet_data.taxon_id; uvp_taxon_id suit la même convention que uvp_taxon_abundance.taxon_key et uvp_object_sizes.taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified). C’est la même jointure que explore.filet_uvp_abundance utilise en interne pour comparer les deux sources.

**Limites :** Ne montre que les correspondances mapping_status=accepted : un taxon FILET absent d’ici n’a pas (encore) de correspondance UVP retenue, ce n’est pas la preuve qu’aucune proposition n’existe (ambiguous/rejected sont cachées, pas absentes). Table de référence, non datée ni zonée : pas de filtre d’accès par contrat/zone/année.

| Colonne | Type SQL | Définition |
|---|---|---|
| filet_taxon_id | text | Identifiant taxonomique FILET source de la correspondance; voir filet_data.taxon_id. |
| uvp_taxon_id | text | Taxon UVP associé, même convention que taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified). |
| mapping_relation | text | Relation entre le taxon FILET et le taxon UVP (ex. équivalence, taxon plus large); ne pas supposer une équivalence stricte sans le vérifier. |
| mapping_version | text | Version de la correspondance taxonomique retenue; une mise à jour change potentiellement le résultat d’une comparaison. |
| evidence | text | Preuves de correspondance JSON; conserver les paramètres, sources et éventuelles ambiguïtés. |

```sql
SELECT tm.filet_taxon_id, s.taxon_name, s.major_um FROM explore.taxon_mapping tm JOIN explore.uvp_object_sizes s ON s.taxon_key = tm.uvp_taxon_id WHERE tm.filet_taxon_id = 'Calanus finmarchicus' LIMIT 20;
```

## explore.marine_zone_boundaries

Contour géométrique (GeoJSON) des zones maritimes utilisées ailleurs comme marine_zone_key.

**Grain :** Une ligne par zone (zone_key), simplifiée pour un usage cartographique.

**Relations :** zone_key correspond au marine_zone_key des vues d’occurrence (uvp_samples, uvp_taxon_abundance, filet_data, uvp_object_sizes…) : joindre dessus pour dessiner le contour réel d’une zone au lieu d’un simple point ou d’un label.

**Limites :** geometry_geojson est une géométrie simplifiée (Douglas-Peucker, tolérance en degrés dans simplify_tolerance_deg) : ne pas l’utiliser pour un calcul de surface ou d’inclusion de précision — shared_data/geo/zones_registry.geojson dans le dépôt reste la référence à pleine résolution. Parser geometry_geojson côté client (ex. Python : json.loads puis shapely.geometry.shape). Table de référence, non datée ni contractuelle : pas de filtre d’accès par contrat/zone/année.

| Colonne | Type SQL | Définition |
|---|---|---|
| zone_key | text | Clé de la zone maritime, même valeur que marine_zone_key ailleurs dans le warehouse; clé de jointure vers les vues d’occurrence. |
| zone_source | text | Source de la géométrie de la zone (ex. registre IHO Marine Regions, composite NeoLab); voir shared_data/geo/zones_registry.geojson pour le détail. |
| geometry_geojson | text | Contour de la zone en GeoJSON (WGS84), simplifié pour l’affichage; parser côté client (json puis shapely/cartopy), ne pas l’utiliser pour un calcul de précision. |
| simplify_tolerance_deg | double precision | Tolérance de simplification (degrés, Douglas-Peucker) appliquée au contour; plus elle est grande, plus le contour s’écarte de la géométrie officielle. |
| loaded_at | timestamp with time zone | Horodatage du dernier chargement de ce contour par scripts/load_marine_zones.py. |

```sql
SELECT zone_key, geometry_geojson FROM explore.marine_zone_boundaries WHERE zone_key = 'Baie de Baffin';
```

## explore.zone_membership

Toutes les zones maritimes qui couvrent chaque point localisé (profil UVP, sample EcoTaxa, profil CTD, sample FILET), chevauchements compris.

**Grain :** Ligne localisée (row_kind × row_id) × zone qui la couvre; un point dans trois zones superposées = trois lignes.

**Relations :** row_kind=uvp_profile : row_id = uvp_taxon_abundance.profile_id = uvp_samples.uvp_profile_id; ecotaxa_sample : row_id = ecotaxa_sample_id; ctd_profile, filet_sample : id de la table. zone_key = marine_zone_boundaries.zone_key.

**Limites :** Calculée en PostGIS (ST_Covers) sur les coordonnées et les contours à pleine résolution. marine_zone_key des autres vues porte UNE zone choisie au chargement : une zone NeoLab/IHO l’emporte sur une écorégion MEOW (un point de la Baie de Baffin peut aussi être dans « MEOW: West Greenland Shelf »), et AMBIGUOUS signale plusieurs zones NeoLab superposées (ex. Baie d’Ungava dans le composite Nunavik). Un filtre marine_zone_key = X perd donc les points AMBIGUOUS et ne trouve jamais une écorégion MEOW écartée; un filtre par cette vue garde tout. Dire dans la réponse quel filtre est utilisé. Zones de sources différentes superposées : ne pas additionner des résultats de plusieurs zones sans dédoublonner row_id. Ligne sans coordonnées propres mais zone attribuée en amont (ex. profil UVP dont les samples EcoTaxa liés divergent sur la position) : présente avec cette seule zone, geometry_resolution = assigned_without_coordinates; sans coordonnées ni zone, pas de ligne. Vue absente sans PostGIS.

| Colonne | Type SQL | Définition |
|---|---|---|
| row_kind | text | Type de ligne localisée : uvp_profile, ecotaxa_sample, ctd_profile ou filet_sample. |
| row_id | bigint | Identifiant de la ligne dans sa table (uvp_profile_id, ecotaxa_sample_id, id CTD ou FILET), selon row_kind. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| zone_key | text | Clé de la zone maritime, même valeur que marine_zone_key ailleurs dans le warehouse; clé de jointure vers les vues d’occurrence. |
| zone_source | text | Source de la géométrie de la zone (ex. registre IHO Marine Regions, composite NeoLab); voir shared_data/geo/zones_registry.geojson pour le détail. |
| assigned_zone_key | text | Zone unique attribuée au chargement à cette ligne (marine_zone_key), AMBIGUOUS si plusieurs zones se chevauchent. |
| marine_zone_assignment_status | text | assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous. |
| geometry_resolution | text | full : appartenance calculée sur le contour à pleine résolution; simplified : contour simplifié (recharger les zones); assigned_without_coordinates : pas de coordonnées propres, zone reprise de l’attribution amont, non recalculée. |

```sql
SELECT a.taxon_key, SUM(a.n_objects_taxon)/SUM(a.sampled_volume_l)*1000 AS ind_m3 FROM explore.uvp_taxon_abundance a JOIN explore.zone_membership m ON m.row_kind='uvp_profile' AND m.row_id=a.profile_id WHERE m.zone_key='Baie de Baffin' AND a.annotation_policy LIKE 'validated_only:%' GROUP BY 1 LIMIT 20;
```

## explore.copepod_stages

Stades de développement des copépodes : signification, ordre et agrégats des codes de stade FILET, et ce que l’UVP permet (ou non) sur les stades.

**Grain :** Une ligne par code de stade FILET (18 codes).

**Relations :** stage_code = filet_data.stage = filet_uvp_abundance.filet_stage. UVP : aucun champ de stade; un stade n’existe côté UVP que si la catégorie EcoTaxa (taxon_key) le nomme, et sa correspondance avec un stade FILET passe par taxon_mapping, décision d’un biologiste.

**Limites :** Établi : les codes, is_aggregate, filet_has_biomass, et la règle de ne jamais additionner un agrégat (COPEPODID, NAUPLIUS, ALL_STAGES) à ses composants. À confirmer (definition_status) : les libellés, le sens de COP_NS/NAUP_NS et la composition des agrégats (adultes inclus ou non dans COPEPODID); la référence est le dictionnaire FILET du labo, non chargé dans le warehouse — le dire plutôt que présenter ces libellés comme validés. Pour une somme par phase, additionner les stades détaillés OU prendre l’agrégat, jamais les deux. Comparer un total FILET tous stades à l’UVP suppose que l’UVP voit les mêmes stades : le signaler, ne pas le supposer.

| Colonne | Type SQL | Définition |
|---|---|---|
| stage_code | text | Code de stade FILET (N1-N6, NAUP_NS, C1-C5, COP_NS, M, F, COPEPODID, NAUPLIUS, ALL_STAGES); même valeur que filet_data.stage. |
| label_fr | text | Libellé du stade en français; voir definition_status avant de le présenter comme validé. |
| life_phase | text | Phase de développement : nauplius, copépodite, adulte, ou agrégat de plusieurs phases. |
| development_order | integer | Rang de développement (N1=1 … C5=11, adultes=12); NULL pour un stade non précisé ou un agrégat. |
| sex | text | mâle ou femelle pour les adultes M et F; NULL sinon. |
| is_aggregate | boolean | Vrai pour COPEPODID, NAUPLIUS ou ALL_STAGES; éviter leur double comptage avec les sous-stades. |
| aggregate_of | text | Stades que l’agrégat regroupe, avec ce qui reste à confirmer; NULL pour un stade détaillé. |
| filet_has_biomass | boolean | Vrai si l’export FILET fournit une biomasse (µg C/m³) pour ce stade; faux pour les nauplii et ALL_STAGES (absence, pas zéro). |
| definition_status | text | Ce qui reste à confirmer pour ce stade avec le dictionnaire FILET du labo; aucune ligne n’est encore validée par un biologiste. |
| note | text | Remarque sur le stade (règle d’agrégation, absence de biomasse, sens présumé d’un code). |

```sql
SELECT f.stage, s.label_fr, s.life_phase, s.is_aggregate, SUM(f.abundance_depth_ind_m3) FROM explore.filet_data f JOIN explore.copepod_stages s ON s.stage_code = f.stage WHERE NOT s.is_aggregate GROUP BY 1,2,3,4 ORDER BY min(s.development_order);
```

## explore.ecopart_source_metadata

Lignes brutes des métadonnées EcoPart.

**Grain :** Ligne source de métadonnées dans une version et un profil éventuel.

**Relations :** dataset_version_id vers dataset_versions; profile_name correspond au nom natif, pas à une clé globale.

**Limites :** Le grain source member_name/row_number n’est pas exposé : des lignes du même profil peuvent exister. Ne pas enrichir EcoTaxa sans liaison prouvée. Unités dans la source JSON, non harmonisées.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
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
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
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
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
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
| depth_m | double precision | Pression en dbar utilisée comme profondeur en mètres (1 dbar ≈ 0,99 m; écart d’environ 1 % à 2000 m), telle que fournie par le chargeur CTD; pas une profondeur recalculée (TEOS-10). |
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
| depth_m | double precision | Pression en dbar utilisée comme profondeur en mètres (1 dbar ≈ 0,99 m; écart d’environ 1 % à 2000 m), telle que fournie par le chargeur CTD; pas une profondeur recalculée (TEOS-10). |
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

**Limites :** Un échantillon = un filet (ou des filets regroupés) pour une couche min_sample_depth–max_sample_depth et une maille. Hydrobios et Bioness : plusieurs couches superposées par déploiement (profil vertical); 2x1m2 et 4x1m2 : une couche, plusieurs mailles. Détails et chiffres : document filet-organisation (search_documents). Un échantillon peut avoir plusieurs analyses ou filets. Zone ambiguous peut signifier chevauchement de polygones, pas exclusion spatiale. Ne pas assimiler station FILET et station UVP par identifiant.

| Colonne | Type SQL | Définition |
|---|---|---|
| id | bigint | Clé technique de l’échantillon FILET. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
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
| net_mesh_size | numeric | Maille du filet en micromètres (µm), selon le dictionnaire du labo (document filet-samples-metadata). |
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
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| source_row_number | integer | Numéro de ligne dans le fichier source FILET, avant dépliage des stades. |
| sample_id | text | Identifiant natif du sample FILET; qualifier par version. |
| analysis_id | text | Identifiant natif d’analyse FILET; qualifier par sample et version. |
| taxon_id | text | Identifiant taxonomique FILET fourni, texte source; pas un AphiaID supposé. |
| stage | text | Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES. Signification et ordre : explore.copepod_stages. |
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
| net_mesh_size | numeric | Maille du filet en micromètres (µm), selon le dictionnaire du labo (document filet-samples-metadata). |
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
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| source_row_number | integer | Numéro de ligne dans le fichier source FILET, avant dépliage des stades. |
| sample_id | text | Identifiant natif du sample FILET; qualifier par version. |
| analysis_id | text | Identifiant natif d’analyse FILET; qualifier par sample et version. |
| taxon_id | text | Identifiant taxonomique FILET fourni, texte source; pas un AphiaID supposé. |
| stage | text | Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES. Signification et ordre : explore.copepod_stages. |
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
| net_mesh_size | numeric | Maille du filet en micromètres (µm), selon le dictionnaire du labo (document filet-samples-metadata). |
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

## explore.filet_deployments

Déploiements FILET : engin, type de trait, couches de profondeur, mailles et analyses, une ligne par mise à l’eau.

**Grain :** Déploiement FILET (deployment_id) dans une version; agrège explore.filet_samples.

**Relations :** deployment_id vers filet_samples.deployment_id (même dataset_version_id) pour descendre aux échantillons, puis filet_data pour les abondances.

**Limites :** sampling_layout « couches superposées » = profil vertical (Hydrobios, Bioness); « une couche, plusieurs mailles » = filets simultanés de mailles différentes (2x1m2, 4x1m2) : comparer des mailles, pas des profondeurs. Latitude et longitude sont la moyenne des échantillons du déploiement. tow_type V-Tow et O-Tow : libellés source non définis dans le dictionnaire du labo. Détails : document filet-organisation.

| Colonne | Type SQL | Définition |
|---|---|---|
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| deployment_id | text | Identifiant natif de déploiement FILET. |
| sampling_year | integer | Année de prélèvement fournie dans les métadonnées FILET. |
| sampling_platform | text | Plateforme de prélèvement fournie par la source FILET. |
| station_name | text | Libellé de station FILET fourni par la source. |
| deployment_datetime_start | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| deployment_datetime_end | timestamp without time zone | Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC. |
| latitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| longitude | double precision | Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement. |
| marine_zone_name | text | Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet. |
| gear | text | Équipement FILET déclaré par la source. |
| tow_type | text | Type de trait FILET déclaré par la source. |
| cast_number | text | Numéro de cast fourni dans les métadonnées FILET. |
| n_samples | bigint | Nombre d’échantillons FILET du déploiement (un par filet et couche, ou filets regroupés). |
| n_layers | bigint | Nombre de couches de profondeur distinctes (min_sample_depth–max_sample_depth) du déploiement. |
| n_meshes | bigint | Nombre de mailles distinctes du déploiement. |
| meshes_um | text | Mailles du déploiement en µm, séparées par des virgules. |
| depth_top_m | numeric | Profondeur la plus haute échantillonnée par le déploiement (m). |
| depth_bottom_m | numeric | Profondeur la plus basse échantillonnée par le déploiement (m). |
| layers | text | Couches de profondeur du déploiement, de haut en bas (« min–max » en m). |
| n_analysed_samples | bigint | Échantillons du déploiement ayant au moins une analyse taxonomique. |
| sampling_layout | text | Disposition : couches superposées (profil vertical), une couche plusieurs mailles, une couche une maille, ou plusieurs couches et mailles. |

```sql
SELECT deployment_id, station_name, sampling_year, gear, n_layers, layers, meshes_um, n_analysed_samples FROM explore.filet_deployments WHERE sampling_layout = 'couches superposées' AND n_analysed_samples > 0 ORDER BY n_layers DESC LIMIT 20;
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
| depth_m | double precision | Pression en dbar utilisée comme profondeur en mètres (1 dbar ≈ 0,99 m; écart d’environ 1 % à 2000 m), telle que fournie par le chargeur CTD; pas une profondeur recalculée (TEOS-10). |
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
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| station_id | text | Station déclarée pour le rapprochement; consulter match_method et evidence. |
| filet_sample_id | bigint | Clé TECHNIQUE de l’échantillon FILET : filet_samples.id. |
| filet_analysis_id | bigint | Clé technique d’analyse FILET; NULL si rapprochement sans analyse. |
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
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

**Limites :** Pour une comparaison sur la même couche d’eau, préférer explore.filet_uvp_compare(max_km, max_hours, same_station, station_if_no_position, uvp_taxon, filet_taxon_pattern, filet_stages, min_size_um, max_size_um, esd|major, validated_only, best_only, min_filet_ug_c_per_ind, filet_stations) et explore.filet_uvp_pairs(max_km, max_hours, same_station, station_if_no_position, filet_stations); garder les critères demandés par l’utilisateur et, si la requête dépasse 30 s, la refaire par stations (filet_stations) : paires par distance et temps, abondance UVP intégrée sur le trait de filet (tranches vides comprises), stades agrégés refusés avec leurs parties; une ligne par échantillon filet : compter les couples par filet_deployment_id; méthode et tests dans le document filet-uvp-comparaison (search_documents). La vue ne filtre PAS m.match_status : exiger accepted si nécessaire. La jointure FILET par identifiants natifs et UVP par profil/taxon n’isole pas toutes les versions ou annotation_policy : risque de multiplication. Le dénominateur FILET est répété par bin UVP; ne pas le sommer. Cette vue n’est pas un comparatif scientifique validé; qualifier versions, profondeur, stades et mapping avant calcul.

| Colonne | Type SQL | Définition |
|---|---|---|
| match_id | bigint | Clé technique de la correspondance FILET–UVP. |
| dataset_version_id | bigint | Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ. |
| station_id | text | Station déclarée pour le rapprochement; consulter match_method et evidence. |
| filet_sample_id | bigint | Clé TECHNIQUE de l’échantillon FILET : filet_samples.id. |
| filet_analysis_id | bigint | Clé technique d’analyse FILET; NULL si rapprochement sans analyse. |
| uvp_profile_id | bigint | Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier. |
| time_gap_hours | numeric | Écart temporel FILET–UVP enregistré, en heures. |
| match_status | text | Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés. |
| taxon_filet | text | Identifiant taxonomique FILET source du mapping; pas un AphiaID supposé. |
| filet_stage | text | Stade FILET conservé dans la comparaison; ne pas additionner agrégats et détails. Signification : explore.copepod_stages. |
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
