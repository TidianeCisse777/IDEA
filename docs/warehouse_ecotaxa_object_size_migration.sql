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

CREATE TABLE IF NOT EXISTS warehouse.ecotaxa_acquisition (
    acquisition_id text PRIMARY KEY,
    sample_id bigint NOT NULL REFERENCES warehouse.ecotaxa_sample,
    pixel_size_mm double precision
);
COMMENT ON TABLE warehouse.ecotaxa_acquisition IS
    'Une ligne par acquisition EcoTaxa (GET /acquisition/{id}); porte la calibration pixel->mm utilisee pour convertir area_px/esd_px/major_px/minor_px.';
COMMENT ON COLUMN warehouse.ecotaxa_acquisition.pixel_size_mm IS
    'Taille reelle d''un pixel, en mm (free column "pixel" de l''acquisition EcoTaxa); NULL si le projet ne la fournit pas, auquel cas aucune conversion en unite reelle n''est possible pour ses objets.';

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
    o.depth_min_m AS object_depth_min_m, o.depth_max_m AS object_depth_max_m,
    b.id AS uvp_bin_id, b.depth_min_m, b.depth_max_m, b.sampled_volume_l,
    o.area_px, o.esd_px, o.major_px, o.minor_px, ac.pixel_size_mm,
    (o.esd_px * ac.pixel_size_mm * 1000) AS esd_um,
    (o.major_px * ac.pixel_size_mm * 1000) AS major_um,
    (o.minor_px * ac.pixel_size_mm * 1000) AS minor_um,
    (o.area_px * (ac.pixel_size_mm * 1000) ^ 2) AS area_um2
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa ul ON ul.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample e ON e.id = ul.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id = e.id
LEFT JOIN warehouse.ecotaxa_acquisition ac ON ac.acquisition_id = o.acquisition_id
LEFT JOIN warehouse.uvp_object_bin ob ON ob.ecotaxa_object_id = o.id
LEFT JOIN warehouse.uvp_bin b ON b.id = ob.uvp_bin_id;

COMMENT ON VIEW explore.uvp_object_sizes IS
    'Un objet EcoTaxa identifie par ligne, avec sa taille reelle (esd_um/major_um/minor_um/area_um2) quand la calibration pixel de son acquisition est connue (NULL sinon : ne pas supposer une taille absente egale a zero). '
    'Grain distinct de explore.uvp_taxon_abundance (agregee par bin/taxon) et de explore.uvp_particle_sizes (non taxonomique) : ici, taxon et taille sont sur la meme ligne. '
    'sampled_volume_l est un attribut du bin, repete sur chaque objet de ce bin : pour une densite par taxon et gamme de taille, agreger le volume une seule fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id), comme pour explore.uvp_particle_sizes, avant de diviser le compte d''objets filtres par ce volume. '
    'esd_px/major_px/minor_px/area_px sont les valeurs source EcoTaxa (Zooprocess), non recalculees; les colonnes _um/_um2 sont calculees ici a partir de pixel_size_mm, qui n''existe pas pour tous les projets.';
