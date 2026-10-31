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

    EXECUTE $sql$
        CREATE OR REPLACE VIEW explore.marine_zone_boundaries AS
        SELECT zone_key, zone_source, ST_AsGeoJSON(geom) AS geometry_geojson, simplify_tolerance_deg, loaded_at
        FROM warehouse.marine_zone
    $sql$;
    EXECUTE $sql$
        COMMENT ON VIEW explore.marine_zone_boundaries IS
            'Un contour de zone maritime par ligne, en GeoJSON (WGS84, EPSG:4326), simplifie pour l''affichage. geometry_geojson se parse avec json puis shapely/cartopy cote client (ex. shapely.geometry.shape(json.loads(geometry_geojson))). Grain reference, non lie a un contrat/version : ne pas confondre avec marine_zone_key des vues d''occurrence (profils, echantillons), qui reste la cle a utiliser pour filtrer ou joindre. Contour simplifie : ne pas l''utiliser pour un calcul de surface ou d''inclusion de precision; shared_data/geo/zones_registry.geojson reste la reference a pleine resolution.'
    $sql$;
END
$$;
