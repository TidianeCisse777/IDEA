-- Additive migration: a PostGIS-backed table for the zone boundaries already
-- used by zone assignment and the navigator (shared_data/geo/zones_registry.geojson),
-- so an agent connected only through SQL can get a real zone shape, not just a
-- zone name. Before this, marine_zone_key was a text label everywhere in the
-- warehouse; the geometry existed only as a local file read by Python scripts
-- and the navigator app, unreachable from DbHub/MCP. Found missing live when
-- asked for a map with real zone contours (see ROADMAP, 31 octobre 2026).
--
-- Loaded (and kept in sync) by scripts/load_marine_zones.py, not by this file:
-- geometry data belongs in a loader, not hand-written into a migration. This
-- file only creates the table and view, idempotently, so a fresh deploy has
-- the right shape even before the loader has run (table starts empty).
--
-- PostGIS is not a trusted extension: a non-superuser owner cannot create it
-- (same constraint as the navigator's spatial filter, see deploy's
-- ensure_postgis). Docker init runs as the database superuser, so the
-- extension attempt below succeeds there directly; deploy_warehouse_postgres.py
-- also attempts it, gracefully, before applying this file. If neither could
-- create it (managed hosting, no superuser access yet), skip this migration's
-- objects instead of failing the whole deploy: the rest of the warehouse does
-- not need it.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS postgis;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PostGIS non activable par ce role (superuser requis): warehouse.marine_zone non cree.';
END
$$;

DO $$
BEGIN
    IF to_regtype('public.geometry') IS NULL THEN
        RAISE NOTICE 'PostGIS indisponible: warehouse.marine_zone non cree (contours de zone absents pour les agents; le reste du warehouse fonctionne).';
        RETURN;
    END IF;

    EXECUTE $sql$
        CREATE TABLE IF NOT EXISTS warehouse.marine_zone (
            zone_key text PRIMARY KEY,
            zone_source text,
            geom geometry(MultiPolygon, 4326) NOT NULL,
            simplify_tolerance_deg double precision NOT NULL,
            loaded_at timestamptz NOT NULL DEFAULT now()
        )
    $sql$;
    EXECUTE $sql$
        COMMENT ON TABLE warehouse.marine_zone IS
            'Contours des zones maritimes (shared_data/geo/zones_registry.geojson), simplifies pour un usage SQL/cartographique; charges par scripts/load_marine_zones.py. Reference non datee et non contractuelle, comme taxon_mapping : exemptee de la securite par ligne.'
    $sql$;
    EXECUTE $sql$
        COMMENT ON COLUMN warehouse.marine_zone.simplify_tolerance_deg IS
            'Tolerance de simplification (degres, Douglas-Peucker) appliquee par le chargeur; un contour simplifie n''est pas la geometrie officielle a pleine resolution, qui reste shared_data/geo/zones_registry.geojson.'
    $sql$;
    EXECUTE 'CREATE INDEX IF NOT EXISTS marine_zone_geom_idx ON warehouse.marine_zone USING GIST (geom)';
    -- Full-resolution contour, the same geometry the loaders test points against
    -- (shapely covers on zones_registry.geojson): zone membership is computed on it,
    -- never on the simplified display contour.
    EXECUTE 'ALTER TABLE warehouse.marine_zone ADD COLUMN IF NOT EXISTS geom_full geometry(MultiPolygon, 4326)';
    EXECUTE $sql$
        COMMENT ON COLUMN warehouse.marine_zone.geom_full IS
            'Contour a pleine resolution (zones_registry.geojson, rendu valide si besoin), utilise pour l''appartenance d''un point a une zone (explore.zone_membership); geom reste le contour simplifie pour l''affichage.'
    $sql$;
    EXECUTE 'CREATE INDEX IF NOT EXISTS marine_zone_geom_full_idx ON warehouse.marine_zone USING GIST (geom_full)';

    EXECUTE $sql$
        CREATE OR REPLACE VIEW explore.marine_zone_boundaries AS
        SELECT zone_key, zone_source, ST_AsGeoJSON(geom) AS geometry_geojson, simplify_tolerance_deg, loaded_at
        FROM warehouse.marine_zone
    $sql$;
    EXECUTE $sql$
        COMMENT ON VIEW explore.marine_zone_boundaries IS
            'Un contour de zone maritime par ligne, en GeoJSON (WGS84, EPSG:4326), simplifie pour l''affichage. geometry_geojson se parse avec json puis shapely/cartopy cote client (ex. shapely.geometry.shape(json.loads(geometry_geojson))). Grain reference, non lie a un contrat/version : ne pas confondre avec marine_zone_key des vues d''occurrence (profils, echantillons), qui reste la cle a utiliser pour filtrer ou joindre. Contour simplifie : ne pas l''utiliser pour un calcul de surface ou d''inclusion de precision; shared_data/geo/zones_registry.geojson reste la reference a pleine resolution.'
    $sql$;

    -- Every zone covering each located row, overlaps included. marine_zone_key on the
    -- occurrence tables holds one zone chosen by the loaders (a NeoLab/IHO zone wins
    -- over a MEOW ecoregion; AMBIGUOUS when several NeoLab zones overlap, e.g. Baie
    -- d'Ungava inside the Nunavik composite), which hides those rows from a filter on
    -- any of them. Row security of the underlying tables applies.
    EXECUTE $sql$
        CREATE OR REPLACE VIEW explore.zone_membership AS
        WITH located AS (
            SELECT 'uvp_profile'::text AS row_kind, id AS row_id, dataset_version_id, latitude, longitude,
                   marine_zone_key, marine_zone_assignment_status FROM warehouse.uvp_profile
            UNION ALL
            SELECT 'ecotaxa_sample', id, dataset_version_id, lat_avg, lon_avg,
                   marine_zone_key, marine_zone_assignment_status FROM warehouse.ecotaxa_sample
            UNION ALL
            SELECT 'ctd_profile', id, dataset_version_id, latitude, longitude,
                   marine_zone_key, marine_zone_assignment_status FROM warehouse.ctd_profile
            UNION ALL
            SELECT 'filet_sample', id, dataset_version_id, latitude, longitude,
                   marine_zone_key, marine_zone_assignment_status FROM warehouse.filet_sample
        )
        SELECT l.row_kind, l.row_id, l.dataset_version_id, z.zone_key, z.zone_source,
               l.marine_zone_key AS assigned_zone_key, l.marine_zone_assignment_status,
               CASE WHEN z.geom_full IS NULL THEN 'simplified' ELSE 'full' END AS geometry_resolution
        FROM located l
        JOIN warehouse.marine_zone z
          ON ST_Covers(COALESCE(z.geom_full, z.geom), ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326))
        WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL
        UNION ALL
        -- No own coordinates but a zone assigned upstream (e.g. a UVP profile whose
        -- linked EcoTaxa samples disagree on position keeps the samples' zone): kept
        -- with that zone only, flagged, so a zone filter does not silently drop it.
        SELECT l.row_kind, l.row_id, l.dataset_version_id, l.marine_zone_key, z.zone_source,
               l.marine_zone_key, l.marine_zone_assignment_status, 'assigned_without_coordinates'
        FROM located l
        LEFT JOIN warehouse.marine_zone z ON z.zone_key = l.marine_zone_key
        WHERE (l.latitude IS NULL OR l.longitude IS NULL) AND l.marine_zone_assignment_status = 'assigned'
    $sql$;
    EXECUTE $sql$
        COMMENT ON VIEW explore.zone_membership IS
            'Une ligne par (ligne localisee, zone qui la couvre) : profils UVP (row_id = uvp_profile_id), samples EcoTaxa (ecotaxa_sample_id), profils CTD, samples FILET. Calculee en PostGIS (ST_Covers) a partir des coordonnees et des contours a pleine resolution, chevauchements inclus : un point dans trois zones superposees donne trois lignes. '
            'assigned_zone_key est la zone unique retenue au chargement : une zone NeoLab/IHO l''emporte sur une ecoregion MEOW, et AMBIGUOUS signale plusieurs zones NeoLab superposees (ex. Baie d''Ungava dans le composite Nunavik). '
            'Pour filtrer par zone sans perdre les points AMBIGUOUS (assigned_zone_key = AMBIGUOUS quand plusieurs zones se chevauchent), joindre ici : ex. uvp_taxon_abundance a JOIN zone_membership m ON m.row_kind = ''uvp_profile'' AND m.row_id = a.profile_id WHERE m.zone_key = ''Baie de Baffin''. '
            'Les zones de sources differentes (zones NeoLab/IHO, ecoregions MEOW, composites) se chevauchent : ne pas sommer des resultats de plusieurs zones sans dedoublonner row_id. Une ligne sans coordonnees propres mais avec une zone attribuee en amont apparait avec cette seule zone et geometry_resolution = assigned_without_coordinates (non recalculee, chevauchements inconnus); sans coordonnees ni zone, pas de ligne. geometry_resolution = simplified signale un contour non recharge a pleine resolution (relancer scripts/load_marine_zones.py).'
    $sql$;
END
$$;
