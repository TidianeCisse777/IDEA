"""Dictionnaire métier versionné; aucune valeur ni disponibilité supposée."""


def view(purpose, grain, joins, caveats, example):
    return dict(purpose=purpose, grain=grain, joins=joins, caveats=caveats, example=example)


VIEWS = {
    'uvp_projects': view(
        'Inventaire agrégé des projets UVP liés à EcoTaxa/EcoPart.',
        'Projet EcoTaxa × projet EcoPart × campagne; EcoTaxa peut être NULL.',
        'Navigation vers uvp_samples par ecotaxa_project_id et ecopart_project_id; sélectionner la campagne.',
        'Ne pas sommer des projets qui réutilisent les mêmes profils. La zone MIN est un libellé représentatif, pas toute la couverture. Pas de dataset_version_id dans cette vue : auditer les versions dans dataset_versions et les vues détaillées.',
        'SELECT * FROM explore.uvp_projects LIMIT 20;'),
    'uvp_samples': view(
        'Métadonnées des profils UVP liés à un sample EcoTaxa.',
        'Profil UVP × liaison sample EcoTaxa; plusieurs liaisons par profil possibles.',
        'uvp_profile_id = uvp_taxon_abundance.profile_id ou ecopart_bins.profile_id; ecotaxa_sample_id = ecotaxa_ctd_profile.ecotaxa_sample_id.',
        'INNER JOIN : les profils sans sample EcoTaxa lié sont absents. COUNT(DISTINCT uvp_profile_id) pour compter les profils. Les zones préfèrent EcoTaxa puis EcoPart.',
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
        'profile_id vers uvp_samples.uvp_profile_id; bin_id vers ecopart_bins.bin_id. Isoler annotation_policy et dataset_version_id.',
        'Formule : n_objects_taxon / sampled_volume_l × 1000, individus/m³. Agréger par SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000, pas par moyenne simple. La vue ajoute des zéros sur tous les bins uniquement pour les taxons observés dans ce profil et cette annotation_policy; un taxon absent du profil entier ne reçoit pas de zéro. all_loaded_objects inclut les objets non validés. Ne pas sommer le même volume sur plusieurs taxons.',
        'SELECT profile_id,taxon_key,annotation_policy,SUM(n_objects_taxon)/SUM(sampled_volume_l)*1000 AS ind_m3 FROM explore.uvp_taxon_abundance GROUP BY 1,2,3 LIMIT 20;'),
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
    'dataset_version_id': 'Clé technique de version de la source de cette vue; voir explore.dataset_versions. Ne pas joindre des sources différentes par simple égalité de ce champ.',
    'metadata_dataset_version_id': 'Version des métadonnées FILET liées; peut être NULL si aucune métadonnée ne correspond.',
    'uvp_dataset_version_id': 'Version de la source du profil UVP; distincte de la version CTD.',
    'ctd_dataset_version_id': 'Version de la source du profil CTD.',
    'ecopart_project_id': 'Identifiant natif du projet EcoPart; distinct de celui du projet EcoTaxa.',
    'ecotaxa_project_id': 'Identifiant natif du projet EcoTaxa; distinct de celui du projet EcoPart.',
    'uvp_profile_id': 'Clé technique du profil UVP; équivaut à profile_id dans les vues de bins et abondances.',
    'profile_id': 'Clé technique du profil UVP; équivaut à uvp_samples.uvp_profile_id.',
    'ctd_profile_id': 'Clé technique du profil CTD; pas une clé d’alignement des mesures individuelles.',
    'ecotaxa_sample_id': 'Clé technique du sample EcoTaxa; distincte de son identifiant natif.',
    'ecotaxa_native_sample_id': 'Identifiant natif du sample EcoTaxa; qualifier par projet/version.',
    'ecopart_sample_id': 'Identifiant natif du sample EcoPart, si fourni.',
    'ecotaxa_profile_id': 'Identifiant de profil fourni dans les métadonnées EcoTaxa; pas une clé technique UVP.',
    'ecotaxa_object_id': 'Clé technique de l’objet EcoTaxa; utiliser DISTINCT si une jointure peut multiplier ses lignes.',
    'object_id': 'Identifiant natif de l’objet EcoTaxa, qualifié par son sample/source.',
    'bin_id': 'Clé technique du bin EcoPart.', 'uvp_bin_id': 'Clé technique du bin EcoPart lié à l’objet; NULL si non apparié.',
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
    'taxon_name': 'Libellé taxonomique EcoTaxa fourni; ne prouve pas un mapping FILET ni une validation.',
    'uvp_taxon': 'Clé taxonomique UVP du mapping accepté; même convention que taxon_key.',
    'taxon_filet': 'Identifiant taxonomique FILET source du mapping; pas un AphiaID supposé.',
    'annotation_status': 'Statut d’annotation EcoTaxa chargé; NULL signifie inconnu, pas validated.',
    'annotation_policy': 'Politique de sélection des objets et projet EcoTaxa; all_loaded_objects inclut tous les objets chargés, pas uniquement les validés.',
    'stage': 'Stade FILET source; distinguer détails et agrégats COPEPODID, NAUPLIUS, ALL_STAGES.',
    'filet_stage': 'Stade FILET conservé dans la comparaison; ne pas additionner agrégats et détails.',
    'is_aggregate': 'Vrai pour COPEPODID, NAUPLIUS ou ALL_STAGES; éviter leur double comptage avec les sous-stades.',
    'sampled_volume_l': 'Volume échantillonné du bin EcoPart, en litres; ne pas le répéter dans une somme multi-taxons.',
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
    'object_count': 'Nombre d’objets déclaré par les métadonnées source, pas un recomptage de tous les objets chargés.',
    'nb_validated': 'Nombre validé déclaré dans les métadonnées EcoTaxa; ne qualifie pas chaque objet chargé.',
    'nb_predicted': 'Nombre prédit déclaré dans les métadonnées EcoTaxa.',
    'nb_dubious': 'Nombre douteux déclaré dans les métadonnées EcoTaxa.',
    'nb_unclassified': 'Nombre non classé déclaré dans les métadonnées EcoTaxa.',
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
