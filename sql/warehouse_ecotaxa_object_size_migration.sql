-- Additive migration: store the raw Zooprocess morphometrics EcoTaxa already
-- carries per object (area, esd, major/minor axis, in pixels) and the
-- per-acquisition pixel calibration needed to convert them to real units.
--
-- Confirmed live against the EcoTaxa API (object_set/{project}/query and
-- GET /object/{id}, /acquisition/{id}): these are EcoTaxa "free columns",
-- named per project (obj_free_cols maps a stable label like "area" or "esd"
-- to a project-specific slot such as "n01"); the label is queryable directly
-- as fre.<label> (e.g. fre.area, fre.esd). Not every project defines every
-- label (UVP6 projects seen so far have no esd column) and a label EcoTaxa
-- does not know for that project is silently dropped from the row instead of
-- returned as null, shifting later columns — a loader must request only the
-- labels a project's own obj_free_cols actually has, never a fixed list.
--
-- Pixel calibration (mm per pixel) is not an object field: it lives on the
-- acquisition (GET /acquisition/{acquisition_id}.free_columns.pixel, in
-- mm/pixel; duplicated on the process). It is not exposed as a field in
-- object_set/query (prefixes acq./pro. silently drop there too), so it must
-- be fetched once per distinct acquisition and stored separately.
ALTER TABLE warehouse.ecotaxa_object
    ADD COLUMN IF NOT EXISTS area_px double precision,
    ADD COLUMN IF NOT EXISTS esd_px double precision,
    ADD COLUMN IF NOT EXISTS major_px double precision,
    ADD COLUMN IF NOT EXISTS minor_px double precision;
COMMENT ON COLUMN warehouse.ecotaxa_object.area_px IS 'Aire Zooprocess de l''objet, en pixels; valeur source EcoTaxa (free column "area"), non recalculee.';
COMMENT ON COLUMN warehouse.ecotaxa_object.esd_px IS 'Diametre spherique equivalent Zooprocess, en pixels; valeur source EcoTaxa (free column "esd") quand le projet la fournit, sinon NULL.';
COMMENT ON COLUMN warehouse.ecotaxa_object.major_px IS 'Axe majeur de l''ellipse ajustee, en pixels; valeur source EcoTaxa (free column "major").';
COMMENT ON COLUMN warehouse.ecotaxa_object.minor_px IS 'Axe mineur de l''ellipse ajustee, en pixels; valeur source EcoTaxa (free column "minor").';

-- Last enrichment (8 novembre 2026): what EcoTaxa gives per object and the warehouse
-- did not keep. Checked live on project 149 (/object_set/149/query): obj.objtime
-- "09:32:28", obj.classif_who 2006, obj.classif_when "2024-02-20T14:36:15",
-- img.file_name "1670/0097.jpg" (served at https://ecotaxa.obs-vlfr.fr/vault/<file>),
-- and the ZooProcess free columns perim., feret, circ., elongation, mean, convarea,
-- common to the UVP5, UVP6 and Zooscan projects (LOKI names its features otherwise).
-- Filled by scripts/populate_ecotaxa_objects.py --refresh; NULL until then.
ALTER TABLE warehouse.ecotaxa_object
    ADD COLUMN IF NOT EXISTS sun_position text,
    ADD COLUMN IF NOT EXISTS classif_who integer,
    ADD COLUMN IF NOT EXISTS classif_when timestamptz,
    ADD COLUMN IF NOT EXISTS classif_auto_score double precision,
    ADD COLUMN IF NOT EXISTS perim_px double precision,
    ADD COLUMN IF NOT EXISTS feret_px double precision,
    ADD COLUMN IF NOT EXISTS circularity double precision,
    ADD COLUMN IF NOT EXISTS elongation double precision,
    ADD COLUMN IF NOT EXISTS mean_grey double precision,
    ADD COLUMN IF NOT EXISTS convex_area_px double precision,
    ADD COLUMN IF NOT EXISTS image_file text;
COMMENT ON COLUMN warehouse.ecotaxa_object.image_file IS 'Chemin de l''image dans le stockage EcoTaxa (img.file_name, ex. 1670/0097.jpg); l''adresse complète est https://ecotaxa.obs-vlfr.fr/vault/ suivi de ce chemin (explore.ecotaxa_objects.image_uri). Le chemin seul évite de répéter le préfixe pour 15 M objets.';
-- image_uri was filled with the full address on 8 novembre 2026: move it to image_file (one-time, guarded).
UPDATE warehouse.ecotaxa_object SET image_file = substr(image_uri, 35), image_uri = NULL
WHERE image_uri LIKE 'https://ecotaxa.obs-vlfr.fr/vault/%';
COMMENT ON COLUMN warehouse.ecotaxa_object.sun_position IS 'Position du soleil calculée par EcoTaxa (obj.sunpos), telle que fournie : D jour, A aube, U crépuscule, N nuit, ? indéterminé; un espace quand EcoTaxa ne l''a pas calculée (9,65 M objets sur 15 M au 8 novembre 2026). Sens vérifié sur les données : élévation solaire moyenne +20° (D), -21° (N), -7° le matin (A), -8° le soir (U).';
COMMENT ON COLUMN warehouse.ecotaxa_object.classif_who IS 'Identifiant EcoTaxa de la personne qui a classé l''objet à la main (obj.classif_who); pas de nom.';
COMMENT ON COLUMN warehouse.ecotaxa_object.classif_when IS 'Date de la dernière classification manuelle dans EcoTaxa (obj.classif_when).';
COMMENT ON COLUMN warehouse.ecotaxa_object.classif_auto_score IS 'Score de la prédiction automatique EcoTaxa (obj.classif_auto_score), souvent NULL pour un objet validé.';
COMMENT ON COLUMN warehouse.ecotaxa_object.perim_px IS 'Périmètre ZooProcess, en pixels (free column "perim.").';
COMMENT ON COLUMN warehouse.ecotaxa_object.feret_px IS 'Diamètre de Feret maximal ZooProcess, en pixels (free column "feret").';
COMMENT ON COLUMN warehouse.ecotaxa_object.circularity IS 'Circularité ZooProcess (free column "circ."), sans unité, 1 = disque.';
COMMENT ON COLUMN warehouse.ecotaxa_object.elongation IS 'Élongation ZooProcess (free column "elongation"), sans unité.';
COMMENT ON COLUMN warehouse.ecotaxa_object.mean_grey IS 'Niveau de gris moyen de l''objet (free column "mean"), échelle de l''image source.';
COMMENT ON COLUMN warehouse.ecotaxa_object.convex_area_px IS 'Aire de l''enveloppe convexe ZooProcess, en pixels (free column "convarea").';

CREATE TABLE IF NOT EXISTS warehouse.ecotaxa_acquisition (
    acquisition_id text PRIMARY KEY,
    sample_id bigint NOT NULL REFERENCES warehouse.ecotaxa_sample,
    pixel_size_mm double precision
);
COMMENT ON TABLE warehouse.ecotaxa_acquisition IS
    'Une ligne par acquisition EcoTaxa (GET /acquisition/{id}); porte la calibration pixel->mm utilisee pour convertir area_px/esd_px/major_px/minor_px.';
COMMENT ON COLUMN warehouse.ecotaxa_acquisition.pixel_size_mm IS
    'Taille reelle d''un pixel, en mm (free column "pixel" de l''acquisition EcoTaxa); NULL si le projet ne la fournit pas, auquel cas aucune conversion en unite reelle n''est possible pour ses objets.';

-- The acquisition's "pixel" value is in millimetres for UVP5 and Zooscan
-- projects (0.085-0.174 observed) but in micrometres for UVP6 projects (73
-- observed, the UVP6 nominal pixel size): read as millimetres everywhere, UVP6
-- sizes came out 1000 times too large (4 novembre 2026). The raw value and the
-- unit read are now kept; rows loaded before are corrected once, here, by the
-- same rule as the loader (populate_ecotaxa_objects.pixel_size): a value of 1 or
-- more is micrometres. Only rows never corrected (pixel_unit_read IS NULL) change.
ALTER TABLE warehouse.ecotaxa_acquisition
    ADD COLUMN IF NOT EXISTS pixel_size_raw double precision,
    ADD COLUMN IF NOT EXISTS pixel_unit_read text;
UPDATE warehouse.ecotaxa_acquisition
SET pixel_size_raw = pixel_size_mm,
    pixel_unit_read = CASE WHEN pixel_size_mm >= 1 THEN 'um' ELSE 'mm' END,
    pixel_size_mm = CASE WHEN pixel_size_mm >= 1 THEN pixel_size_mm / 1000 ELSE pixel_size_mm END
WHERE pixel_unit_read IS NULL AND pixel_size_mm IS NOT NULL;
COMMENT ON COLUMN warehouse.ecotaxa_acquisition.pixel_size_raw IS
    'Valeur source du champ "pixel" de l''acquisition EcoTaxa, telle que fournie (mm pour UVP5/Zooscan, µm pour UVP6).';
COMMENT ON COLUMN warehouse.ecotaxa_acquisition.pixel_unit_read IS
    'Unité retenue pour pixel_size_raw : mm, ou um (valeur >= 1, cas UVP6, divisée par 1000 dans pixel_size_mm).';

-- Row security for warehouse.ecotaxa_acquisition is registered in the central
-- spec list in warehouse_access_control.sql (which runs after this file and
-- applies ENABLE/FORCE ROW LEVEL SECURITY + the access_scope policy there,
-- same as every other table) rather than duplicated here.

-- Grain : un objet EcoTaxa identifie, avec sa taille reelle (quand calculable)
-- et le bin EcoPart auquel il est rattache. Distinct de explore.uvp_objects
-- (qui n'expose pas la taille) pour ne pas changer le contrat d'une vue deja
-- testee; meme jointure sous-jacente.
CREATE OR REPLACE VIEW explore.uvp_object_sizes AS
SELECT
    u.id AS uvp_profile_id, u.dataset_version_id, u.sample_name,
    u.marine_zone_key, u.marine_zone_assignment_status, u.sampled_at,
    o.id AS ecotaxa_object_id, o.object_id, o.acquisition_id,
    o.category_id AS taxon_id, o.category_name AS taxon_name, o.annotation_status,
    CASE WHEN o.category_id IS NOT NULL THEN 'ecotaxa:id:'||o.category_id
         WHEN o.category_name IS NOT NULL THEN 'ecotaxa:name:'||o.category_name
         ELSE 'warehouse:unclassified' END AS taxon_key,
    o.depth_min_m AS object_depth_min_m, o.depth_max_m AS object_depth_max_m,
    b.id AS uvp_bin_id, b.depth_min_m, b.depth_max_m, b.sampled_volume_l,
    o.area_px, o.esd_px, o.major_px, o.minor_px, ac.pixel_size_mm,
    -- ESD: source value, else the diameter of the disc of the same area (its definition). Most recent UVP6
    -- projects give the area but no ESD (11.4 M objects, 11 November 2026). Where both exist they are equal
    -- (ratio 1.0000 on 200 000 objects). Without this, a filter on esd_um silently dropped those projects.
    (coalesce(o.esd_px, 2 * sqrt(o.area_px / pi())) * ac.pixel_size_mm * 1000) AS esd_um,
    (o.major_px * ac.pixel_size_mm * 1000) AS major_um,
    (o.minor_px * ac.pixel_size_mm * 1000) AS minor_um,
    (o.area_px * (ac.pixel_size_mm * 1000) ^ 2) AS area_um2,
    -- Source sample and project: a profile can be linked to several EcoTaxa samples holding copies of the same
    -- images (199 GreenEdge 2016 profiles: project 149 and 20880 or 20890). Keep one project per profile.
    e.id AS ecotaxa_sample_id, e.project_id AS ecotaxa_project_id
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa ul ON ul.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample e ON e.id = ul.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id = e.id
LEFT JOIN warehouse.ecotaxa_acquisition ac ON ac.acquisition_id = o.acquisition_id
-- Bin scoped to this row's profile, as in explore.uvp_objects (EcoPart migration):
-- an EcoTaxa sample linked to several profiles or versions must not fan out.
LEFT JOIN (warehouse.uvp_object_bin ob
    JOIN warehouse.uvp_bin b ON b.id = ob.uvp_bin_id)
    ON ob.ecotaxa_object_id = o.id AND b.profile_id = u.id
WHERE EXISTS (
    -- Copies: a profile linked to several EcoTaxa samples (199 GreenEdge 2016 profiles: projects 149 and 20880 /
    -- 20890, same images) keeps one, warehouse.uvp_canonical_sample: the copy whose position agrees with the
    -- profile's (cited CTD), the smallest project on a tie. Nothing counts twice.
    SELECT 1 FROM warehouse.uvp_canonical_sample k WHERE k.uvp_profile_id = u.id AND k.ecotaxa_sample_id = e.id);

COMMENT ON VIEW explore.uvp_object_sizes IS
    'Un objet EcoTaxa identifie par ligne, avec sa taille reelle (esd_um/major_um/minor_um/area_um2) quand la calibration pixel de son acquisition est connue (NULL sinon : ne pas supposer une taille absente egale a zero). '
    'Grain distinct de explore.uvp_taxon_abundance (agregee par bin/taxon) et de explore.uvp_particle_sizes (non taxonomique) : ici, taxon et taille sont sur la meme ligne. '
    'sampled_volume_l est un attribut du bin, repete sur chaque objet de ce bin : pour une densite par taxon et gamme de taille, agreger le volume une seule fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id), comme pour explore.uvp_particle_sizes, avant de diviser le compte d''objets filtres par ce volume. '
    'esd_px/major_px/minor_px/area_px sont les valeurs source EcoTaxa (Zooprocess), non recalculees; les colonnes _um/_um2 sont calculees ici a partir de pixel_size_mm, qui n''existe pas pour tous les projets. '
    'taxon_key suit la meme convention que uvp_taxon_abundance.taxon_key : pour comparer a une abondance FILET du meme taxon, joindre explore.taxon_mapping sur uvp_taxon_id = taxon_key (mapping_status accepted uniquement), comme explore.filet_uvp_abundance le fait en interne.';

-- explore.uvp_objects without the EcoTaxa copies, for existing databases. Kept identical to its definition in
-- warehouse_ecopart_migration.sql (tests/test_warehouse_documents.py checks it), which only runs on a new one.
CREATE OR REPLACE VIEW explore.uvp_objects AS
SELECT
    u.id AS uvp_profile_id, u.dataset_version_id, u.ecopart_project_id,
    u.sample_name, u.cruise_key, u.station_key, u.sampled_at,
    CASE WHEN u.position_source = 'ctd_cite' THEN u.marine_zone_key ELSE COALESCE(e.marine_zone_key,u.marine_zone_key) END AS marine_zone_key,
    CASE WHEN u.position_source = 'ctd_cite' THEN u.marine_zone_name ELSE COALESCE(e.marine_zone_name,u.marine_zone_name) END AS marine_zone_name,
    CASE WHEN u.position_source = 'ctd_cite' THEN u.marine_zone_version ELSE COALESCE(e.marine_zone_version,u.marine_zone_version) END AS marine_zone_version,
    CASE WHEN u.position_source = 'ctd_cite' THEN u.marine_zone_assignment_status ELSE COALESCE(e.marine_zone_assignment_status,u.marine_zone_assignment_status) END AS marine_zone_assignment_status,
    e.id AS ecotaxa_sample_id, e.project_id AS ecotaxa_project_id, e.sample_orig_id,
    o.id AS ecotaxa_object_id, o.object_id, o.acquisition_id, o.process_id,
    o.category_id AS taxon_id, o.category_name AS taxon_name, o.annotation_status,
    o.depth_min_m AS object_depth_min_m, o.depth_max_m AS object_depth_max_m,
    b.id AS uvp_bin_id, b.source_bin_key, b.depth_min_m, b.depth_max_m,
    b.sampled_volume_l, ob.depth_delta_m, ob.mapping_method, ob.mapping_status, o.image_uri
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa ul ON ul.uvp_profile_id=u.id
JOIN warehouse.ecotaxa_sample e ON e.id=ul.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id=e.id
LEFT JOIN (warehouse.uvp_object_bin ob
    JOIN warehouse.uvp_bin b ON b.id=ob.uvp_bin_id)
    ON ob.ecotaxa_object_id=o.id AND b.profile_id=u.id
WHERE EXISTS (
    -- Copies: a profile linked to several EcoTaxa samples (199 GreenEdge 2016 profiles: projects 149 and 20880 /
    -- 20890, same images) keeps one, warehouse.uvp_canonical_sample: the copy whose position agrees with the
    -- profile's (cited CTD), the smallest project on a tie. Nothing counts twice.
    SELECT 1 FROM warehouse.uvp_canonical_sample k WHERE k.uvp_profile_id = u.id AND k.ecotaxa_sample_id = e.id);
