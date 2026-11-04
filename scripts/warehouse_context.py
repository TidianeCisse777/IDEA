"""Dictionnaire métier versionné; aucune valeur ni disponibilité supposée."""


def view(purpose, grain, joins, caveats, example):
    return dict(purpose=purpose, grain=grain, joins=joins, caveats=caveats, example=example)


GRAPHICS = view(
    'Règles de graphiques NeoLab. Utiliser Python : pandas pour manipuler les résultats SQL, '
    'Matplotlib pour les figures scientifiques statiques; seaborn facultatif pour les distributions. '
    'Cartopy avec Matplotlib pour les cartes statiques et projections; Folium pour les cartes '
    'interactives exportées en HTML. GeoPandas/Shapely/pyproj seulement si des opérations de '
    'géométrie ou de reprojection sont nécessaires. cmocean pour les palettes de variables '
    'océanographiques, avec barre de couleur et unités explicites; conserver cividis en repli. '
    'Pour l’analyse physique océanographique : oceans fournit des utilitaires, gsw (GSW/TEOS-10) '
    'les propriétés thermodynamiques; xarray convient aux données multidimensionnelles/NetCDF. '
    'Ces bibliothèques sont facultatives selon le besoin; ne pas les installer ni les appeler toutes '
    'systématiquement. Vérifier pour chaque fonction les entrées requises, unités, convention '
    'scientifique et domaine de validité; toute grandeur dérivée conserve formule et provenance. '
    'Avec gsw, distinguer salinité pratique/absolue et température in situ/conservative; ne pas '
    'substituer directement pression et profondeur. Clarifier les hypothèses manquantes avant calcul. '
    'Plotly uniquement si une interaction est demandée ou utile à une exploration explicitée; '
    'fournir alors un HTML autonome. Vérifier les bibliothèques installées avant exécution; leur '
    'mention ici ne signifie pas qu’elles sont disponibles. Respecter un choix explicite de l’utilisateur.',
    'Le graphique représente le grain documenté et un résultat réellement calculé. Agréger dans SQL '
    'avant transfert. DbHub limite les réponses à 1 000 lignes : contrôler le nombre attendu et toute '
    'indication de résultat tronqué; ne jamais tracer un sous-ensemble tronqué comme une population complète. '
    'Une base vide produit un constat d’absence de données, aucun graphique avec données inventées. '
    'NULL et zéro restent distincts. Ne pas interpoler, lisser, normaliser ou exclure des valeurs sans '
    'méthode explicite; demander une clarification si cela change le sens scientifique.',
    'Style par défaut : fond blanc, police DejaVu Sans 11 pt, titre descriptif court en français, '
    'axes avec noms et unités vérifiées, légende lisible, grille fine gris clair et marges sans texte coupé. '
    'Couleurs catégorielles adaptées au daltonisme, palette séquentielle cividis pour une quantité continue. '
    'Conserver couleurs et échelles cohérentes entre panneaux comparables. Pas de 3D décorative ou '
    'double axe sans justification. Profils : profondeur en ordonnée croissante vers le bas; '
    'échelle logarithmique uniquement explicitée et compatible avec zéros/valeurs négatives. '
    'Conserver les deux dénominateurs FILET séparés et appliquer l’agrégation UVP pondérée par volume. '
    'Cartographie : vérifier le CRS; les coordonnées du warehouse sont en degrés WGS84. '
    'Avec Cartopy, séparer projection d’affichage et transform des données : PlateCarree pour les '
    'longitudes/latitudes WGS84, projection polaire adaptée à l’Arctique si pertinente. '
    'Ordre des points : Cartopy (longitude, latitude), Folium [latitude, longitude], '
    'GeoJSON [longitude, latitude]. Exclure explicitement les coordonnées manquantes/hors domaine '
    'sans les inventer. Calculer les distances en géodésique/PostGIS, pas en degrés ni en pixels. '
    'Conserver la version des zones et les ambiguïtés; distinguer source, statut et concentration '
    'dans la légende. Identifier les fonds/tuiles et leurs attributions. Les tuiles, bibliothèques '
    'JavaScript distantes et fonds Cartopy peuvent nécessiter Internet ou un cache local : '
    'ne pas annoncer une carte Folium autonome hors ligne sans l’avoir vérifiée. '
    'Privilégier les fonds locaux/caches; confirmer tout téléchargement lourd.',
    'Afficher un cartouche de statut : Exploratoire par défaut, pas une probabilité de confiance. '
    'Convention confirmed (#007B88, trait plein), exploratory (#B87514, tirets), uncertain '
    '(#737C86, pointillés); toujours ajouter un libellé ou symbole pour ne pas dépendre de la couleur. '
    'confirmed exige une validation scientifique explicitement documentée; un match accepted ou un test '
    'technique réussi ne suffit pas. uncertain signale les limites connues, sans inventer de valeurs '
    'ou d’intervalles. Si la couleur code un taxon ou une quantité, garder le statut dans le cartouche '
    'et les libellés. Aucune interprétation biologique, aucun ajustement statistique ni intervalle '
    'd’incertitude inventé. Conserver requête SQL, paramètres, versions, méthode, exclusions et limites '
    'dans un fichier de provenance accompagnant la figure. Produire un PNG à 300 dpi et un SVG pour '
    'les figures statiques, le CSV exact tracé et le script Python reproductible; indiquer les chemins '
    'réels des fichiers créés. Fichiers : les écrire dans le dossier de travail courant avec des chemins '
    'relatifs (jamais un chemin absolu recopié à la main), puis vérifier qu’ils existent (ex. ls) et donner '
    'le chemin absolu réellement affiché par cette vérification. Rendu : relire l’image finale APRÈS la '
    'dernière modification du script, pas une version antérieure; si une retouche suit la relecture, '
    'relire de nouveau. Abondance par taxon : tracer la politique validated_only à côté de '
    'all_loaded_objects (ou expliquer pourquoi une seule), avec le nombre de profils de chacune, car '
    'all_loaded_objects inclut les objets prédits non validés. Signaler toute limite restante.',
    "SELECT topic,purpose,grain,relations,caveats FROM catalogue.warehouse_context WHERE topic='graphs';",
)


# Views registered in VIEWS that may legitimately be absent from a deployment:
# marine_zone_boundaries needs PostGIS, which a non-superuser managed-hosting
# owner cannot always create (see deploy_warehouse_postgres.py's
# ensure_postgis and docs/warehouse_marine_zone_migration.sql). publish()
# treats every other VIEWS entry as mandatory; this is the one exception.
OPTIONAL_VIEWS = {'marine_zone_boundaries', 'zone_membership'}

VIEWS = {
    'ecotaxa_projects': view(
        'Inventaire de TOUS les projets EcoTaxa chargés, quel que soit l’instrument (UVP, Zooscan, LOKI…), avec leurs objets par statut d’annotation.',
        'Un projet EcoTaxa par ligne.',
        'ecotaxa_project_id vers ecotaxa_samples, ecotaxa_objects, uvp_projects, uvp_samples. has_uvp_profiles dit si des profils UVP (donc des volumes) existent.',
        'Point d’entrée pour toute question sur « les projets » ou « les objets EcoTaxa » en général : uvp_projects ne couvre que les projets liés à un profil UVP. Les compteurs sont la somme des compteurs des samples (recalculés depuis les objets chargés). Dire dans la réponse quel périmètre est couvert (tous les projets, ou seulement ceux liés à l’UVP). Des projets peuvent être des copies les uns des autres (149 = 20880 + 20890, établi par les comptes par profil) : voir la fiche ecotaxa_samples avant d’additionner.',
        'SELECT ecotaxa_project_id, ecotaxa_project_title, instrument, n_objects, n_validated, n_predicted FROM explore.ecotaxa_projects ORDER BY n_objects DESC;'),
    'ecotaxa_samples': view(
        'Tous les samples EcoTaxa, tous projets et instruments, avec position, date, zone et compteurs d’objets par statut d’annotation.',
        'Un sample EcoTaxa par ligne.',
        'ecotaxa_sample_id vers ecotaxa_objects.ecotaxa_sample_id et uvp_samples.ecotaxa_sample_id; ecotaxa_project_id vers ecotaxa_projects.',
        'Pour compter ou comparer des statuts d’annotation, partir d’ici (rapide) et non de ecotaxa_objects. uvp_samples ne montre que les samples liés à un profil UVP et peut répéter un sample lié à plusieurs profils; ici une ligne = un sample. Deux projets peuvent porter des copies des mêmes images (ex. 149 = 20880 + 20890) : vérifier avant d’additionner des projets. Une copie a toujours d’autres identifiants d’objet, et un titre proche ne prouve rien : comparer les comptes par profil UVP ou par sample; sans cette comparaison, écrire « copie possible, non vérifiée » plutôt que l’affirmer. Pas de volume échantillonné : pas d’abondance ici.',
        'SELECT ecotaxa_project_id, SUM(nb_validated) AS valides, SUM(nb_predicted) AS predits FROM explore.ecotaxa_samples GROUP BY 1;'),
    'ecotaxa_objects': view(
        'Tous les objets EcoTaxa (15 M), tous projets et instruments : taxon, statut d’annotation, profondeur, taille.',
        'Un objet EcoTaxa par ligne.',
        'ecotaxa_sample_id vers ecotaxa_samples; ecotaxa_project_id vers ecotaxa_projects; ecotaxa_object_id = uvp_objects.ecotaxa_object_id pour les objets liés à un profil UVP.',
        'Toujours filtrer par ecotaxa_project_id ou ecotaxa_sample_id et agréger dans la requête : un balayage complet dépasse le délai de 30 s. Pour de simples comptes par statut, ecotaxa_samples suffit. Tailles réelles (_um) NULL sans calibration pixel (LOKI notamment), jamais zéro. Pas d’abondance (ind/m³) sans volume : passer par les vues UVP.',
        'SELECT taxon_name, annotation_status, COUNT(*) FROM explore.ecotaxa_objects WHERE ecotaxa_project_id = 12063 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;'),
    'ctd_profiles': view(
        'Tous les profils CTD Amundsen chargés, liés ou non à EcoTaxa.',
        'Un profil CTD par ligne.',
        'ctd_profile_id vers ctd_measurements; zone_membership (row_kind = ctd_profile, row_id = ctd_profile_id).',
        'ecotaxa_ctd_profile ne montre que les profils liés à un sample EcoTaxa (une ligne par liaison); ici chaque profil une fois. max_depth_m est la profondeur maximale mesurée.',
        'SELECT cruise_key, COUNT(*), MIN(sampled_at), MAX(sampled_at) FROM explore.ctd_profiles GROUP BY 1;'),
    'ctd_measurements': view(
        'Mesures CTD (température, salinité, densité, oxygène, nitrate, fluorescence, pH) de tous les profils, format long.',
        'Profil CTD × scan × variable.',
        'ctd_profile_id vers ctd_profiles pour position, date et zone.',
        'Filtrer variable_key et ctd_profile_id avant d’agréger (5 M lignes). Unité dans unit telle que fournie; ne convertir pression/profondeur ni salinité sans le dire. Pour un profil moyen, moyenner d’abord par profil et classe de profondeur, puis entre profils.',
        "SELECT ctd_profile_id, depth_m, value AS temperature FROM explore.ctd_measurements WHERE variable_key = 'TE90' AND ctd_profile_id = 1 ORDER BY depth_m;"),
    'uvp_projects': view(
        'Inventaire agrégé des projets UVP liés à EcoTaxa/EcoPart.',
        'Projet EcoTaxa × projet EcoPart × campagne; EcoTaxa peut être NULL.',
        'Navigation vers uvp_samples par ecotaxa_project_id et ecopart_project_id; sélectionner la campagne.',
        'Ne pas sommer des projets qui réutilisent les mêmes profils. marine_zone_key/name (MIN) ne montrent qu’UNE zone : pour savoir si un projet touche une zone, filtrer sur marine_zone_keys (toutes les zones attribuées à ses profils/samples), ex. WHERE \'Baie de Baffin\' = ANY(marine_zone_keys); les points en chevauchement de zones (AMBIGUOUS) se retrouvent par explore.zone_membership. Pas de dataset_version_id dans cette vue : auditer les versions dans dataset_versions et les vues détaillées. '
        'ecotaxa_project_title est le nom natif du projet EcoTaxa, pour affichage (légende, étiquette) : NULL si le projet n’a pas été chargé dans warehouse.ecotaxa_project, et ne pas l’utiliser comme clé (deux projets pourraient en théorie partager un titre) — grouper/joindre sur ecotaxa_project_id.',
        'SELECT * FROM explore.uvp_projects LIMIT 20;'),
    'uvp_samples': view(
        'Métadonnées des profils UVP liés à un sample EcoTaxa.',
        'Profil UVP × liaison sample EcoTaxa; plusieurs liaisons par profil possibles.',
        'uvp_profile_id = uvp_taxon_abundance.profile_id ou ecopart_bins.profile_id; ecotaxa_sample_id = ecotaxa_ctd_profile.ecotaxa_sample_id.',
        'INNER JOIN : les profils sans sample EcoTaxa lié sont absents. COUNT(DISTINCT uvp_profile_id) pour compter les profils. Les zones préfèrent EcoTaxa puis EcoPart. '
        'ecotaxa_project_title est le nom natif du projet, pour affichage uniquement (peut être NULL); ecotaxa_project_id reste la clé stable.',
        'SELECT uvp_profile_id,sample_name,station_key,sampled_at FROM explore.uvp_samples LIMIT 20;'),
    'uvp_objects': view(
        'Objets EcoTaxa associés aux profils UVP, avec un bin EcoPart éventuel.',
        'Profil UVP × objet EcoTaxa × correspondance de bin éventuelle.',
        'uvp_profile_id vers uvp_samples; uvp_bin_id vers ecopart_bins.bin_id. ecotaxa_object_id est la clé technique de l’objet.',
        'Les jointures peuvent multiplier les objets : compter DISTINCT ecotaxa_object_id au périmètre choisi. Un bin NULL ne signifie pas volume nul. Ne pas joindre les objets à tous les scans CTD du profil. taxon_id/taxon_name/annotation_status peuvent manquer; aucune validation taxonomique implicite.',
        'SELECT taxon_id,taxon_name,COUNT(DISTINCT ecotaxa_object_id) FROM explore.uvp_objects GROUP BY 1,2 LIMIT 20;'),
    'ecopart_bins': view(
        'Bins échantillonnés EcoPart, y compris sans objet, et ligne brute PAR.',
        'Version EcoPart × profil × bin disposant d’une ligne source.',
        'profile_id vers uvp_samples.uvp_profile_id; bin_id vers uvp_taxon_abundance.bin_id.',
        'Conserver les bins sans objet dans le dénominateur. source_row_json conserve les champs et unités sources : ne pas inférer leur unité à partir du nom seul.',
        'SELECT profile_id,bin_id,depth_min_m,depth_max_m,sampled_volume_l FROM explore.ecopart_bins LIMIT 20;'),
    'uvp_taxon_abundance': view(
        'Abondances UVP dérivées des objets EcoTaxa et volumes EcoPart.',
        'Version dérivée × profil × bin × taxon_key × annotation_policy.',
        'profile_id vers uvp_samples.uvp_profile_id; bin_id vers ecopart_bins.bin_id. Isoler annotation_policy et dataset_version_id. '
        'ecotaxa_project_id vers uvp_projects.ecotaxa_project_id.',
        'Formule : n_objects_taxon / sampled_volume_l × 1000, individus/m³. Agréger par SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000, pas par moyenne simple. Filtre de zone complet (y compris points AMBIGUOUS) : JOIN explore.zone_membership m ON m.row_kind=\'uvp_profile\' AND m.row_id=profile_id. La vue ajoute des zéros sur tous les bins uniquement pour les taxons observés dans ce profil et cette annotation_policy; un taxon absent du profil entier ne reçoit pas de zéro. annotation_policy vaut all_loaded_objects:ecotaxa_project=N (tous les objets chargés : validés, prédits, douteux et jamais classés) ou validated_only:ecotaxa_project=N (validés seulement, statut V d’EcoTaxa) : toujours filtrer une seule politique et la nommer dans la réponse; comparer les deux pour montrer la part du prédit. Attention avec validated_only : un profil sans aucun objet validé de ce taxon n’a pas de ligne (pas de zéro, l’annotation y est peut-être incomplète), donc le volume de référence diffère de all_loaded_objects; toujours donner, pour chaque politique, le nombre de profils et le volume total utilisés, et ne pas présenter l’écart entre politiques comme une différence biologique. Ne pas sommer le même volume sur plusieurs taxons. '
        'marine_zone_key/name/assignment_status viennent directement de uvp_profile : disponibles même quand explore.uvp_samples est vide pour ce profil (pas de sample EcoTaxa lié) — ne pas passer par uvp_samples pour la zone, elle est déjà ici.',
        'SELECT profile_id,taxon_key,annotation_policy,SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000 AS ind_m3 FROM explore.uvp_taxon_abundance GROUP BY 1,2,3 LIMIT 20;'),
    'uvp_particle_sizes': view(
        'Spectre de tailles des particules UVP (produit EcoPart LPM), sans annotation taxonomique.',
        'Profil × bin (profondeur) × size_class_key.',
        'uvp_profile_id vers uvp_samples.uvp_profile_id; uvp_bin_id vers le bin de profondeur. Grain distinct de '
        'uvp_taxon_abundance : pas de taxon_key, pas de correspondance directe avec une espèce ou un stade.',
        'sampled_volume_l est un attribut du bin, répété sur chaque size_class_key de ce bin : sommer ce volume '
        'directement sur plusieurs classes de taille le compte une fois par classe au lieu d’une fois par bin, et '
        'fausse la densité (division par un volume trop grand). Pour une densité sur une gamme de taille, agréger '
        'le volume une seule fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id), sommer '
        'particle_count et ce volume par bin sur les size_class_key choisies, puis diviser et ×1000 pour des '
        'particules/m³; ne pas mélanger des bins de profondeur différente dans une même somme sans le dire. '
        'particle_count et observed_volume_m3 sont les valeurs source, non recalculées. Ne pas comparer directement '
        'à une abondance taxonomique FILET ou UVP : la comparaison porte sur une taille, pas une identification.',
        'WITH per_bin AS (SELECT uvp_bin_id, MIN(sampled_volume_l) AS vol_l, SUM(particle_count) AS n '
        'FROM explore.uvp_particle_sizes WHERE size_min_um>=200 AND size_max_um<=1000 GROUP BY uvp_bin_id) '
        'SELECT SUM(n)/SUM(vol_l)*1000 AS n_m3 FROM per_bin;'),
    'uvp_object_sizes': view(
        'Un objet EcoTaxa identifié (taxon) par ligne, avec sa taille réelle quand elle est calculable.',
        'Objet EcoTaxa (un par ligne), avec le bin EcoPart auquel il est rattaché.',
        'uvp_profile_id vers uvp_samples.uvp_profile_id; uvp_bin_id vers le bin de profondeur; taxon_id/taxon_name '
        'comme sur explore.uvp_objects. Distinct de uvp_taxon_abundance (agrégée par bin/taxon, sans taille) et de '
        'uvp_particle_sizes (taille sans taxon) : ici, taxon et taille sont sur la même ligne. taxon_key suit la '
        'même convention que uvp_taxon_abundance.taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified) : '
        'pour comparer à une abondance FILET du même taxon, joindre explore.taxon_mapping sur '
        'uvp_taxon_id = taxon_key, comme explore.filet_uvp_abundance le fait en interne.',
        'esd_um/major_um/minor_um/area_um2 sont NULL quand la calibration pixel de l’acquisition EcoTaxa '
        '(pixel_size_mm) est inconnue — ne pas traiter un NULL comme une taille nulle ni l’exclure silencieusement '
        'sans le signaler. esd_px/major_px/minor_px/area_px sont les valeurs source EcoTaxa (Zooprocess), non '
        'recalculées; _um/_um2 sont calculées ici. sampled_volume_l est un attribut du bin, répété sur chaque objet '
        'de ce bin : pour une densité par taxon et gamme de taille, agréger ce volume une seule fois par '
        'uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id) avant de diviser, comme pour uvp_particle_sizes. '
        'Un objet peut ne pas être rattaché à un bin (uvp_bin_id NULL) : l’exclure explicitement d’un calcul de '
        'densité plutôt que de le laisser fausser silencieusement une moyenne.',
        'WITH per_bin AS (SELECT uvp_bin_id, MIN(sampled_volume_l) AS vol_l, COUNT(*) AS n '
        'FROM explore.uvp_object_sizes WHERE taxon_name ILIKE \'%calanus%\' AND major_um BETWEEN 500 AND 1000 '
        'AND uvp_bin_id IS NOT NULL GROUP BY uvp_bin_id) SELECT SUM(n)/SUM(vol_l)*1000 AS ind_m3 FROM per_bin;'),
    'taxon_mapping': view(
        'Correspondance taxonomique FILET↔UVP retenue (statut accepted uniquement).',
        'Une ligne par paire filet_taxon_id/uvp_taxon_id/mapping_version retenue.',
        'filet_taxon_id vers filet_data.taxon_id; uvp_taxon_id suit la même convention que uvp_taxon_abundance.taxon_key '
        'et uvp_object_sizes.taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified). C’est la même jointure '
        'que explore.filet_uvp_abundance utilise en interne pour comparer les deux sources.',
        'Ne montre que les correspondances mapping_status=accepted : un taxon FILET absent d’ici n’a pas (encore) de '
        'correspondance UVP retenue, ce n’est pas la preuve qu’aucune proposition n’existe (ambiguous/rejected sont '
        'cachées, pas absentes). Table de référence, non datée ni zonée : pas de filtre d’accès par contrat/zone/année.',
        'SELECT tm.filet_taxon_id, s.taxon_name, s.major_um FROM explore.taxon_mapping tm '
        'JOIN explore.uvp_object_sizes s ON s.taxon_key = tm.uvp_taxon_id '
        'WHERE tm.filet_taxon_id = \'Calanus finmarchicus\' LIMIT 20;'),
    'marine_zone_boundaries': view(
        'Contour géométrique (GeoJSON) des zones maritimes utilisées ailleurs comme marine_zone_key.',
        'Une ligne par zone (zone_key), simplifiée pour un usage cartographique.',
        'zone_key correspond au marine_zone_key des vues d’occurrence (uvp_samples, uvp_taxon_abundance, '
        'filet_data, uvp_object_sizes…) : joindre dessus pour dessiner le contour réel d’une zone au lieu d’un '
        'simple point ou d’un label.',
        'geometry_geojson est une géométrie simplifiée (Douglas-Peucker, tolérance en degrés dans '
        'simplify_tolerance_deg) : ne pas l’utiliser pour un calcul de surface ou d’inclusion de précision — '
        'shared_data/geo/zones_registry.geojson dans le dépôt reste la référence à pleine résolution. '
        'Parser geometry_geojson côté client (ex. Python : json.loads puis shapely.geometry.shape). '
        'Table de référence, non datée ni contractuelle : pas de filtre d’accès par contrat/zone/année.',
        'SELECT zone_key, geometry_geojson FROM explore.marine_zone_boundaries WHERE zone_key = \'Baie de Baffin\';'),
    'zone_membership': view(
        'Toutes les zones maritimes qui couvrent chaque point localisé (profil UVP, sample EcoTaxa, profil CTD, sample FILET), chevauchements compris.',
        'Ligne localisée (row_kind × row_id) × zone qui la couvre; un point dans trois zones superposées = trois lignes.',
        'row_kind=uvp_profile : row_id = uvp_taxon_abundance.profile_id = uvp_samples.uvp_profile_id; ecotaxa_sample : row_id = ecotaxa_sample_id; ctd_profile, filet_sample : id de la table. zone_key = marine_zone_boundaries.zone_key.',
        'Calculée en PostGIS (ST_Covers) sur les coordonnées et les contours à pleine résolution. marine_zone_key des autres vues porte UNE zone choisie au chargement : une zone NeoLab/IHO l’emporte sur une écorégion MEOW (un point de la Baie de Baffin peut aussi être dans « MEOW: West Greenland Shelf »), et AMBIGUOUS signale plusieurs zones NeoLab superposées (ex. Baie d’Ungava dans le composite Nunavik). Un filtre marine_zone_key = X perd donc les points AMBIGUOUS et ne trouve jamais une écorégion MEOW écartée; un filtre par cette vue garde tout. Dire dans la réponse quel filtre est utilisé. Zones de sources différentes superposées : ne pas additionner des résultats de plusieurs zones sans dédoublonner row_id. Ligne sans coordonnées propres mais zone attribuée en amont (ex. profil UVP dont les samples EcoTaxa liés divergent sur la position) : présente avec cette seule zone, geometry_resolution = assigned_without_coordinates; sans coordonnées ni zone, pas de ligne. Vue absente sans PostGIS.',
        "SELECT a.taxon_key, SUM(a.n_objects_taxon)/SUM(a.sampled_volume_l)*1000 AS ind_m3 FROM explore.uvp_taxon_abundance a JOIN explore.zone_membership m ON m.row_kind='uvp_profile' AND m.row_id=a.profile_id WHERE m.zone_key='Baie de Baffin' AND a.annotation_policy LIKE 'validated_only:%' GROUP BY 1 LIMIT 20;"),
    'copepod_stages': view(
        'Stades de développement des copépodes : signification, ordre et agrégats des codes de stade FILET, '
        'et ce que l’UVP permet (ou non) sur les stades.',
        'Une ligne par code de stade FILET (18 codes).',
        'stage_code = filet_data.stage = filet_uvp_abundance.filet_stage. UVP : aucun champ de stade; un stade '
        'n’existe côté UVP que si la catégorie EcoTaxa (taxon_key) le nomme, et sa correspondance avec un stade '
        'FILET passe par taxon_mapping, décision d’un biologiste.',
        'Établi : les codes, is_aggregate, filet_has_biomass, et la règle de ne jamais additionner un agrégat '
        '(COPEPODID, NAUPLIUS, ALL_STAGES) à ses composants. À confirmer (definition_status) : les libellés, le '
        'sens de COP_NS/NAUP_NS et la composition des agrégats (adultes inclus ou non dans COPEPODID); la référence '
        'est le dictionnaire FILET du labo, non chargé dans le warehouse — le dire plutôt que présenter ces libellés '
        'comme validés. Pour une somme par phase, additionner les stades détaillés OU prendre l’agrégat, jamais les '
        'deux. Comparer un total FILET tous stades à l’UVP suppose que l’UVP voit les mêmes stades : le signaler, ne '
        'pas le supposer.',
        "SELECT f.stage, s.label_fr, s.life_phase, s.is_aggregate, SUM(f.abundance_depth_ind_m3) FROM explore.filet_data f "
        "JOIN explore.copepod_stages s ON s.stage_code = f.stage WHERE NOT s.is_aggregate GROUP BY 1,2,3,4 "
        "ORDER BY min(s.development_order);"),
    'ecopart_source_metadata': view(
        'Lignes brutes des métadonnées EcoPart.', 'Ligne source de métadonnées dans une version et un profil éventuel.',
        'dataset_version_id vers dataset_versions; profile_name correspond au nom natif, pas à une clé globale.',
        'Le grain source member_name/row_number n’est pas exposé : des lignes du même profil peuvent exister. Ne pas enrichir EcoTaxa sans liaison prouvée. Unités dans la source JSON, non harmonisées.',
        'SELECT * FROM explore.ecopart_source_metadata LIMIT 5;'),
    'ecopart_supplied_zooplankton': view(
        'Lignes ZOO fournies par EcoPart, conservées sans recalcul.', 'Ligne source ZOO dans une version et un profil éventuel.',
        'dataset_version_id vers dataset_versions; profile_name doit être qualifié par sa source/version.',
        'Ne pas confondre ces données fournies avec uvp_taxon_abundance : les exports ZOO peuvent utiliser les vignettes validées, contrairement à all_loaded_objects. Inspecter les champs/unités JSON avant calcul.',
        'SELECT * FROM explore.ecopart_supplied_zooplankton LIMIT 5;'),
    'uvp_ctd': view(
        'Mesures CTD rattachées à un profil UVP.', 'Liaison UVP–CTD × ligne/scan source × variable × canal.',
        'uvp_profile_id vers uvp_samples; ctd_profile_id identifie le profil CTD. Ne pas aligner verticalement par le seul profil.',
        'La présence d’une liaison ne prouve pas l’alignement profondeur/temps de chaque mesure. Valeur/unité/QC doivent être lus ensemble. Ne pas multiplier ces lignes par les objets du profil.',
        'SELECT sample_name,depth_m,variable_key,value,unit,qc FROM explore.uvp_ctd LIMIT 20;'),
    'ecotaxa_ctd_profile': view(
        'Liens EcoTaxa–CTD et preuves, y compris non acceptés.', 'Sample EcoTaxa × profil CTD candidat.',
        'ecotaxa_sample_id vers uvp_samples; ctd_profile_id vers ecotaxa_ctd.',
        'Filtrer match_status selon l’usage; candidat et ambigu ne sont pas des liens acceptés. Consulter relation_type, distance_km, time_gap_minutes et evidence.',
        'SELECT ecotaxa_sample_id,ctd_profile_id,match_status,distance_km,time_gap_minutes FROM explore.ecotaxa_ctd_profile LIMIT 20;'),
    'ecotaxa_ctd': view(
        'Mesures CTD des seuls liens EcoTaxa–CTD acceptés.', 'Sample EcoTaxa × profil CTD accepté × mesure/variable/canal.',
        'ecotaxa_sample_id vers uvp_samples; ctd_profile_id vers ecotaxa_ctd_profile.',
        'Le lien est filtré accepted, mais pas le QC des valeurs. Cette vue n’expose pas toutes les clés source de scan; ne pas supposer une clé unique (profondeur,variable). Aligner verticalement avec une méthode explicite.',
        'SELECT ecotaxa_sample_id,depth_m,variable_key,value,unit,qc FROM explore.ecotaxa_ctd LIMIT 20;'),
    'filet_samples': view(
        'Métadonnées des échantillons FILET et nombre d’analyses.', 'Échantillon FILET technique, dans une version.',
        'id = filet_uvp_matches.filet_sample_id. sample_id natif se qualifie par dataset_version_id.',
        'Un échantillon peut avoir plusieurs analyses ou filets. Zone ambiguous peut signifier chevauchement de polygones, pas exclusion spatiale. Ne pas assimiler station FILET et station UVP par identifiant.',
        'SELECT id,sample_id,station_name,latitude,longitude,n_analyses FROM explore.filet_samples LIMIT 20;'),
    'filet_data': view(
        'Abondances et biomasses FILET fournies, avec métadonnées éventuellement non appariées.',
        'Version d’abondance × sample_id × analysis_id × taxon_id × stage; ligne source conservée.',
        'sample_id + metadata_dataset_version_id vers filet_samples.sample_id + dataset_version_id; ne pas utiliser la version d’abondance à la place de la version des métadonnées.',
        'Valeurs source : ne pas recalculer les volumes ou concentrations. Depth et flowmeter restent deux dénominateurs distincts. Ne pas sommer stades détaillés et agrégats; metadata_matched=false garde la ligne sans inventer de coordonnées. analysis_contract est un libellé source, pas une règle validée de séparation.',
        'SELECT sample_id,analysis_id,taxon_id,stage,abundance_depth_ind_m3,abundance_flowmeter_ind_m3,metadata_matched FROM explore.filet_data LIMIT 20;'),
    'filet_totals': view(
        'Sous-ensemble FILET au stade ALL_STAGES.', 'Même grain que filet_data, limité à stage=ALL_STAGES.',
        'Même contrat de jointure et de versions que filet_data.',
        'Ne pas additionner ALL_STAGES avec les sous-stades. Ne pas mélanger depth et flowmeter. Un total fourni n’autorise pas une équivalence taxonomique avec UVP.',
        'SELECT sample_id,taxon_id,abundance_depth_ind_m3 FROM explore.filet_totals LIMIT 20;'),
    'filet_ctd': view(
        'Mesures CTD rattachées aux échantillons FILET.', 'Sample FILET natif × liaison CTD × mesure.',
        'filet_sample_id est ici le sample_id NATIF texte; dans filet_uvp_matches, filet_sample_id est au contraire la clé technique bigint. Qualifier les versions via les vues sources avant jointure.',
        'Pas de statut de liaison ni de dataset_version_id exposé : ne pas inférer une validation de correspondance ou une unicité inter-version. Lire unit et qc; pas d’alignement vertical implicite.',
        'SELECT filet_sample_id,ctd_profile_id,depth_m,variable_key,value,unit FROM explore.filet_ctd LIMIT 20;'),
    'filet_uvp_matches': view(
        'Correspondances FILET–UVP stockées, avec statut et preuves.', 'Version de rapprochement × candidat FILET–UVP, analyse FILET éventuellement NULL.',
        'filet_sample_id = filet_samples.id; uvp_profile_id = uvp_samples.uvp_profile_id. filet_analysis_id est une clé technique d’analyse, pas analysis_id natif.',
        'Conserver match_status/evidence; ne pas promouvoir un candidat ambigu en accepted après filtrage. Le navigateur filtre ces paires existantes par heure et distance géodésique; il ne crée pas de candidats. La distance spatiale du navigateur n’est pas une colonne de cette vue. Une fenêtre élargie ne récupère pas des paires jamais chargées.',
        "SELECT id,filet_sample_id,uvp_profile_id,time_gap_hours,match_status FROM explore.filet_uvp_matches WHERE match_status='accepted' LIMIT 20;"),
    'filet_uvp_abundance': view(
        'Comparaison des abondances via les liens FILET–UVP et le mapping taxonomique accepté.',
        'Correspondance × ligne FILET/stade × mapping taxonomique × bin UVP; pas une paire unique.',
        'match_id vers filet_uvp_matches.id; uvp_profile_id vers uvp_samples.uvp_profile_id. Les taxons passent par warehouse.taxon_mapping accepted.',
        'La vue ne filtre PAS m.match_status : exiger accepted si nécessaire. La jointure FILET par identifiants natifs et UVP par profil/taxon n’isole pas toutes les versions ou annotation_policy : risque de multiplication. Le dénominateur FILET est répété par bin UVP; ne pas le sommer. Cette vue n’est pas un comparatif scientifique validé; qualifier versions, profondeur, stades et mapping avant calcul.',
        "SELECT * FROM explore.filet_uvp_abundance WHERE match_status='accepted' LIMIT 20;"),
}

COLUMNS = {
    'dataset_version_id': 'Clé technique de version de la source de cette vue; voir catalogue.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ.',
    'metadata_dataset_version_id': 'Version des métadonnées FILET liées; peut être NULL si aucune métadonnée ne correspond.',
    'uvp_dataset_version_id': 'Version de la source du profil UVP; distincte de la version CTD.',
    'ctd_dataset_version_id': 'Version de la source du profil CTD.',
    'ecopart_project_id': 'Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa.',
    'ecotaxa_project_id': 'Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart.',
    'ecotaxa_project_title': 'Nom natif du projet EcoTaxa, pour affichage; NULL si le projet n’a pas été chargé. Ne pas l’utiliser comme clé, préférer ecotaxa_project_id.',
    'uvp_profile_id': 'Clé technique du profil UVP, même nom et même valeur dans toutes les vues UVP : clé de jointure à privilégier.',
    'profile_id': 'Ancien nom de la clé du profil UVP dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_profile_id (présente aussi dans ces vues), à privilégier.',
    'ctd_profile_id': 'Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles.',
    'ecotaxa_sample_id': 'Clé technique du sample EcoTaxa; distincte de son identifiant natif.',
    'ecotaxa_native_sample_id': 'Identifiant natif du sample EcoTaxa; qualifier par projet/version.',
    'ecopart_sample_id': 'Identifiant natif du sample EcoPart, si fourni.',
    'ecotaxa_profile_id': 'Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP.',
    'ecotaxa_object_id': 'Clé technique de l’objet EcoTaxa; utiliser DISTINCT si une jointure peut multiplier ses lignes.',
    'object_id': 'Identifiant natif de l’objet EcoTaxa, qualifié par son sample/source.',
    'bin_id': 'Ancien nom de la clé du bin EcoPart dans ecopart_bins et uvp_taxon_abundance; même valeur que uvp_bin_id, à privilégier.', 'uvp_bin_id': 'Clé technique du bin de profondeur EcoPart, même nom dans toutes les vues UVP; dans uvp_objects/uvp_object_sizes, NULL si l’objet n’est rattaché à aucun bin.',
    'source_bin_key': 'Identifiant du bin dans l’export source.',
    'source_row_number': 'Numéro de ligne dans le fichier source FILET, avant dépliage des stades.',
    'source_row_key': 'Clé de ligne source CTD; conserve le grain original.',
    'scan_key': 'Identifiant de scan source CTD; qualifier par profil et source.',
    'sample_name': 'Nom natif du profil EcoPart; pas un identifiant global.',
    'profile_name': 'Nom du profil dans la ligne source EcoPart; peut être absent ou répété.',
    'sample_orig_id': 'Identifiant original du sample EcoTaxa, utilisé par les liens de provenance.',
    'sample_id': 'Identifiant natif du sample FILET; qualifier par version.',
    'analysis_id': 'Identifiant natif d’analyse FILET; qualifier par sample et version.',
    'filet_analysis_id': 'Clé technique d’analyse FILET; NULL si rapprochement sans analyse.',
    'match_id': 'Clé technique de la correspondance FILET–UVP.',
    'cruise_key': 'Libellé/clé de campagne de la source; pas de normalisation inter-source implicite.',
    'station_key': 'Libellé/clé de station UVP de la source; ne prouve pas une identité inter-source.',
    'station_name': 'Libellé de station FILET fourni par la source.',
    'station_id': 'Station déclarée pour le rapprochement; consulter match_method et evidence.',
    'cast_key': 'Identifiant/libellé de cast du profil UVP.',
    'cast_number': 'Numéro de cast fourni dans les métadonnées FILET.',
    'ctd_station_id': 'Clé de station du profil CTD.',
    'ecotaxa_station_id': 'Station fournie dans les métadonnées EcoTaxa.',
    'ecotaxa_cruise_id': 'Campagne fournie dans les métadonnées EcoTaxa.',
    'source_profile_key': 'Identifiant natif du profil CTD.',
    'ctd_source_profile_key': 'Identifiant natif du profil CTD.',
    'ctd_rosette_filename': 'Nom source de fichier rosette CTD; indice de correspondance, pas une preuve unique suffisante.',
    'instrument': 'Instrument déclaré dans les métadonnées EcoTaxa; NULL ne permet pas d’en inférer le modèle à partir du nom de projet.',
    'taxon_key': 'Clé dérivée : ecotaxa:id:…, ecotaxa:name:… ou warehouse:unclassified; ne pas présenter un libellé ou marqueur comme identifiant taxonomique officiel.',
    'taxon_name': 'Libellé taxonomique EcoTaxa (ex. Copepoda<Multicrustacea), pour lire et afficher; la clé de jointure reste taxon_key/taxon_id. Ne prouve pas un mapping FILET ni une validation.',
    'uvp_taxon': 'Clé taxonomique UVP du mapping accepté; même convention que taxon_key.',
    'taxon_filet': 'Identifiant taxonomique FILET source du mapping; pas un AphiaID supposé.',
    'annotation_status': 'Statut d’annotation EcoTaxa (classif_qual) : validated (V, validé par un humain), predicted (P, classification automatique), dubious (D); NULL = objet jamais classé (ou chargé avant l’ajout du statut), pas validated.',
    'annotation_policy': 'Politique de sélection des objets et projet EcoTaxa : all_loaded_objects:ecotaxa_project=N (tous les objets chargés, validés ou non) ou validated_only:ecotaxa_project=N (annotation_status = validated seulement). Filtrer une seule politique.',
    'ecotaxa_status': 'Statut du projet dans EcoTaxa (ex. Annotate), tel que fourni.',
    'n_samples': 'Nombre de samples EcoTaxa chargés pour ce projet.',
    'n_objects': 'Nombre d’objets chargés du projet (somme de object_count des samples).',
    'n_validated': 'Objets validés (annotation_status = validated) du projet, somme des samples.',
    'n_predicted': 'Objets prédits automatiquement, non validés (annotation_status = predicted), somme des samples.',
    'n_dubious': 'Objets marqués douteux (annotation_status = dubious), somme des samples.',
    'n_unclassified': 'Objets jamais classés (sans statut ni catégorie), somme des samples.',
    'has_uvp_profiles': 'Vrai si au moins un sample du projet est lié à un profil UVP (EcoPart), donc à des volumes échantillonnés.',
    'has_uvp_profile': 'Vrai si ce sample est lié à au moins un profil UVP (voir uvp_samples).',
    'object_datetime': 'Date et heure de l’objet fournies par EcoTaxa; peut être NULL.',
    'object_lat': 'Latitude de l’objet fournie par EcoTaxa (WGS84); souvent celle du sample ou NULL.',
    'object_lon': 'Longitude de l’objet fournie par EcoTaxa (WGS84); souvent celle du sample ou NULL.',
    'max_depth_m': 'Profondeur maximale mesurée dans ce profil CTD, en mètres.',
    'has_ecotaxa_link': 'Vrai si le profil CTD a au moins une liaison acceptée avec un sample EcoTaxa.',
    'variable_name': 'Nom lisible de la variable CTD (référentiel ctd_variable), ex. température, salinité.',
    'marine_zone_keys': 'Toutes les zones attribuées aux profils/samples du projet (tableau, AMBIGUOUS compris); filtrer avec = ANY(marine_zone_keys).',
    'row_kind': 'Type de ligne localisée : uvp_profile, ecotaxa_sample, ctd_profile ou filet_sample.',
    'row_id': 'Identifiant de la ligne dans sa table (uvp_profile_id, ecotaxa_sample_id, id CTD ou FILET), selon row_kind.',
    'assigned_zone_key': 'Zone unique attribuée au chargement à cette ligne (marine_zone_key), AMBIGUOUS si plusieurs zones se chevauchent.',
    'geometry_resolution': 'full : appartenance calculée sur le contour à pleine résolution; simplified : contour simplifié (recharger les zones); assigned_without_coordinates : pas de coordonnées propres, zone reprise de l’attribution amont, non recalculée.',
    'stage': 'Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES. Signification et ordre : explore.copepod_stages.',
    'filet_stage': 'Stade FILET conservé dans la comparaison; ne pas additionner agrégats et détails. Signification : explore.copepod_stages.',
    'stage_code': 'Code de stade FILET (N1-N6, NAUP_NS, C1-C5, COP_NS, M, F, COPEPODID, NAUPLIUS, ALL_STAGES); même valeur que filet_data.stage.',
    'label_fr': 'Libellé du stade en français; voir definition_status avant de le présenter comme validé.',
    'life_phase': 'Phase de développement : nauplius, copépodite, adulte, ou agrégat de plusieurs phases.',
    'development_order': 'Rang de développement (N1=1 … C5=11, adultes=12); NULL pour un stade non précisé ou un agrégat.',
    'sex': 'mâle ou femelle pour les adultes M et F; NULL sinon.',
    'aggregate_of': 'Stades que l’agrégat regroupe, avec ce qui reste à confirmer; NULL pour un stade détaillé.',
    'filet_has_biomass': 'Vrai si l’export FILET fournit une biomasse (µg C/m³) pour ce stade; faux pour les nauplii et ALL_STAGES (absence, pas zéro).',
    'definition_status': 'Ce qui reste à confirmer pour ce stade avec le dictionnaire FILET du labo; aucune ligne n’est encore validée par un biologiste.',
    'note': 'Remarque sur le stade (règle d’agrégation, absence de biomasse, sens présumé d’un code).',
    'is_aggregate': 'Vrai pour COPEPODID, NAUPLIUS ou ALL_STAGES; éviter leur double comptage avec les sous-stades.',
    'sampled_volume_l': 'Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons.',
    'size_class_key': 'Clé de classe de taille EcoPart (produit LPM); grain non taxonomique, distinct de taxon_key.',
    'size_min_um': 'Borne inférieure de la classe de taille, en micromètres; définit la gamme avec size_max_um.',
    'size_max_um': 'Borne supérieure de la classe de taille, en micromètres; définit la gamme avec size_min_um.',
    'size_definition': 'Méthode ou convention EcoPart ayant défini les bornes de taille; ne pas supposer une convention unique entre jeux de données.',
    'particle_count': 'Nombre brut de particules comptées pour la classe de taille et le bin; valeur source, non recalculée.',
    'observed_volume_m3': 'Volume observé par l’instrument pour ce bin, en m³; distinct de sampled_volume_l.',
    'supplied_concentration': 'Concentration fournie par EcoPart pour la classe de taille, si présente; ne pas la substituer à un calcul propre sans vérifier son unité.',
    'concentration_unit': 'Unité de supplied_concentration telle que fournie par EcoPart; vérifier avant toute comparaison entre jeux de données.',
    'area_px': 'Aire Zooprocess de l’objet EcoTaxa, en pixels; valeur source, non recalculée.',
    'esd_px': 'Diamètre sphérique équivalent Zooprocess, en pixels; NULL si le projet EcoTaxa ne fournit pas cette colonne libre.',
    'major_px': 'Axe majeur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée.',
    'minor_px': 'Axe mineur de l’ellipse ajustée par Zooprocess, en pixels; valeur source, non recalculée.',
    'pixel_size_mm': 'Taille réelle d’un pixel pour l’acquisition de l’objet, en mm; NULL si EcoTaxa ne la fournit pas, auquel cas aucune colonne _um/_um2 n’est calculable pour cet objet.',
    'esd_um': 'esd_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle.',
    'major_um': 'major_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle.',
    'minor_um': 'minor_px converti en micromètres via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une taille nulle.',
    'area_um2': 'area_px convertie en micromètres carrés via pixel_size_mm; NULL si pixel_size_mm est NULL, pas une aire nulle.',
    'n_objects_taxon': 'Nombre d’objets du taxon pour le bin et la politique; zéros densifiés selon le contrat de la vue.',
    'abundance_uvp_ind_m3': 'Abondance UVP dérivée en individus/m³ : n_objects_taxon / sampled_volume_l × 1000.',
    'sample_abundance': 'Nombre d’individus attribués par la source FILET, déjà calculé; ne pas recalculer implicitement.',
    'abundance_depth_ind_m3': 'Abondance FILET source en individus/m³, dénominateur volume depth.',
    'abundance_flowmeter_ind_m3': 'Abondance FILET source en individus/m³, dénominateur volume flowmeter.',
    'abundance_filet_depth_ind_m3': 'Abondance FILET source en individus/m³ selon volume depth; répétée par bin dans la comparaison.',
    'abundance_filet_flowmeter_ind_m3': 'Abondance FILET source en individus/m³ selon volume flowmeter; répétée par bin.',
    'biomass_depth_ug_c_m3': 'Biomasse FILET source en µg C/m³ selon volume depth.',
    'biomass_flowmeter_ug_c_m3': 'Biomasse FILET source en µg C/m³ selon volume flowmeter.',
    'depth_calc_net_filtered_vol': 'Volume FILET fourni calculé par profondeur; unité à confirmer dans la documentation source avant conversion.',
    'flowmeter_calc_vol': 'Volume FILET fourni calculé par flowmeter; unité à confirmer dans la source.',
    'net_mesh_size': 'Maille FILET déclarée; unité à confirmer dans la source avant conversion.',
    'subsampling_quantity': 'Quantité de sous-échantillonnage fournie; lire subsampling_unit.',
    'subsampling_unit': 'Unité déclarée du sous-échantillonnage; ne pas la remplacer implicitement.',
    'analysis_contract': 'Contrat d’analyse FILET fourni; aucune règle métier de séparation des contrats validée.',
    'analysis_protocol_id': 'Identifiant source du protocole d’analyse FILET.',
    'metadata_matched': 'Vrai si la ligne FILET rejoint une analyse/métadonnée; faux conserve la ligne sans inventer de contexte.',
    'sampling_year': 'Année de prélèvement fournie dans les métadonnées FILET.',
    'sampling_platform': 'Plateforme de prélèvement fournie par la source FILET.',
    'deployment_id': 'Identifiant natif de déploiement FILET.',
    'number_of_nets': 'Nombre de filets déclaré dans les métadonnées FILET.',
    'sample_nets': 'Description source des filets associés à l’échantillon.',
    'net_sampling_ids': 'Identifiants de prélèvement/filet fournis; conserver leur représentation source.',
    'gear': 'Équipement FILET déclaré par la source.', 'tow_type': 'Type de trait FILET déclaré par la source.',
    'variable_key': 'Code de variable CTD; conserver les codes source et ne pas assimiler des variables sans vérifier définition/unité.',
    'variable_definition': 'Définition source de la variable CTD.',
    'sensor_channel': 'Canal/capteur source CTD; deux canaux ne sont pas des répétitions à moyenner implicitement.',
    'value': 'Valeur CTD fournie; interpréter avec unit, variable_key, sensor_channel et qc.',
    'unit': 'Unité CTD fournie; aucune conversion implicite entre codes/sources.',
    'qc': 'Indicateur qualité source CTD; NULL signifie absent, pas bon.',
    'pressure_dbar': 'Pression CTD en dbar; ne pas assimiler automatiquement à la profondeur en mètres.',
    'distance_km': 'Écart spatial enregistré du lien EcoTaxa–CTD, en kilomètres; pas le seuil spatial FILET–UVP du navigateur.',
    'time_gap_minutes': 'Écart temporel enregistré du lien EcoTaxa–CTD, en minutes.',
    'time_gap_hours': 'Écart temporel FILET–UVP enregistré, en heures.',
    'evidence': 'Preuves de correspondance JSON; conserver les paramètres, sources et éventuelles ambiguïtés.',
    'filet_taxon_id': 'Identifiant taxonomique FILET source de la correspondance; voir filet_data.taxon_id.',
    'uvp_taxon_id': 'Taxon UVP associé, même convention que taxon_key (ecotaxa:id:…/ecotaxa:name:…/warehouse:unclassified).',
    'mapping_relation': 'Relation entre le taxon FILET et le taxon UVP (ex. équivalence, taxon plus large); ne pas supposer une équivalence stricte sans le vérifier.',
    'mapping_version': 'Version de la correspondance taxonomique retenue; une mise à jour change potentiellement le résultat d’une comparaison.',
    'zone_key': 'Clé de la zone maritime, même valeur que marine_zone_key ailleurs dans le warehouse; clé de jointure vers les vues d’occurrence.',
    'zone_source': 'Source de la géométrie de la zone (ex. registre IHO Marine Regions, composite NeoLab); voir shared_data/geo/zones_registry.geojson pour le détail.',
    'geometry_geojson': 'Contour de la zone en GeoJSON (WGS84), simplifié pour l’affichage; parser côté client (json puis shapely/cartopy), ne pas l’utiliser pour un calcul de précision.',
    'simplify_tolerance_deg': 'Tolérance de simplification (degrés, Douglas-Peucker) appliquée au contour; plus elle est grande, plus le contour s’écarte de la géométrie officielle.',
    'loaded_at': 'Horodatage du dernier chargement de ce contour par scripts/load_marine_zones.py.',
    'match_status': 'Statut de la correspondance; accepted est distinct des candidats ambiguous et des liens non acceptés.',
    'match_method': 'Méthode enregistrée de rapprochement; ne pas la déduire du seul statut.',
    'relation_type': 'Nature de la liaison EcoTaxa–CTD déclarée par le rapprochement.',
    'mapping_method': 'Méthode d’association objet–bin EcoPart.',
    'mapping_status': 'Statut de l’association objet–bin; distinct du statut d’annotation taxonomique.',
    'depth_delta_m': 'Écart vertical enregistré pour l’association objet–bin, en mètres.',
    'source_row_json': 'Ligne source complète conservée en JSON; noms et unités non harmonisés. Inspecter avant calcul.',
    'image_uri': 'Référence d’image source de l’objet; sa présence ne garantit pas l’accessibilité de l’image.',
    'acquisition_id': 'Identifiant natif d’acquisition EcoTaxa.', 'process_id': 'Identifiant natif de traitement EcoTaxa.',
    'n_profiles': 'Nombre de profils UVP DISTINCT dans le groupe; groupes potentiellement chevauchants.',
    'n_ecotaxa_samples': 'Nombre de samples EcoTaxa DISTINCT dans le groupe.',
    'n_casts': 'Nombre de clés de cast DISTINCT non NULL dans le groupe.',
    'n_analyses': 'Nombre d’analyses FILET DISTINCT liées à l’échantillon.',
    'object_count': 'Nombre d’objets chargés de ce sample (recalculé depuis les objets chargés).',
    'nb_validated': 'Nombre d’objets chargés de ce sample avec annotation_status = validated (recalculé depuis les objets).',
    'nb_predicted': 'Nombre d’objets chargés de ce sample avec annotation_status = predicted (recalculé depuis les objets).',
    'nb_dubious': 'Nombre d’objets chargés de ce sample avec annotation_status = dubious (recalculé depuis les objets).',
    'nb_unclassified': 'Nombre d’objets chargés de ce sample sans statut (jamais classés), recalculé depuis les objets.',
    'marine_zone_key': 'Clé de zone maritime attribuée; consulter source, version et statut.',
    'marine_zone_name': 'Libellé de zone; dans uvp_projects, MIN ne représente pas toutes les zones du projet.',
    'marine_zone_source': 'Référentiel utilisé pour l’attribution de zone.',
    'marine_zone_version': 'Version du référentiel ou de l’attribution de zone.',
    'marine_zone_assignment_status': 'assigned, ambiguous, outside ou unresolved; un chevauchement peut être ambiguous.',
}


def column_description(view_name, column):
    if column == 'id':
        return 'Clé technique de l’échantillon FILET.' if view_name == 'filet_samples' else 'Clé technique de la correspondance FILET–UVP.'
    if column == 'taxon_id':
        return ('Identifiant taxonomique FILET fourni, texte source; pas un AphiaID supposé.'
                if view_name.startswith('filet_') else 'Identifiant de catégorie EcoTaxa fourni; pas une équivalence FILET implicite.')
    if column == 'filet_sample_id':
        return ('Identifiant NATIF texte du sample FILET; pas filet_samples.id.' if view_name == 'filet_ctd'
                else 'Clé TECHNIQUE de l’échantillon FILET : filet_samples.id.')
    if column in COLUMNS:
        return COLUMNS[column]
    if column.startswith(('latitude', 'longitude')):
        return 'Coordonnée géographique source en degrés WGS84; suffixe min/max = étendue agrégée, pas un point de prélèvement.'
    if column in ('depth_min_m', 'depth_max_m', 'source_depth_m', 'depth_m',
                  'object_depth_min_m', 'object_depth_max_m', 'min_sample_depth', 'max_sample_depth'):
        return 'Profondeur en mètres : bin, objet, mesure ou prélèvement selon le préfixe; ne pas confondre leurs grains.'
    if column in ('depth_min', 'depth_max'):
        return 'Borne de profondeur fournie dans les métadonnées EcoTaxa; unité à vérifier dans la source.'
    if column in ('sampled_at', 'ctd_sampled_at', 'filet_sampled_at', 'uvp_sampled_at',
                  'datetime_min', 'datetime_max', 'deployment_datetime_start', 'deployment_datetime_end', 'start_at', 'end_at'):
        return 'Horodatage source ou borne agrégée selon le nom; vérifier le type SQL et le fuseau. Le rapprochement FILET existant interprète ses dates sans fuseau en UTC.'
    raise KeyError(f'Colonne non documentée : {view_name}.{column}')
