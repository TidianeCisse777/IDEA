-- FILET–UVP : paires par proximité (espace, temps, station en option) et comparaison d'abondances sur la
-- même couche d'eau, avec choix des taxons, des stades FILET, de la taille UVP et du statut d'annotation.
--
-- explore.filet_uvp_pairs(max_km, max_hours, require_same_station)
--     Paires candidates : distance (haversine, km), écart de temps (h), station identique ou non, nombre de
--     candidats par échantillon FILET et rang (le plus proche d'abord : distance/max_km + écart/max_hours).
--     Position UVP : EcoPart, sinon moyenne des samples EcoTaxa du profil (uvp_position_source).
--     max_km NULL : pas de critère spatial. Un profil UVP sans position ne passe un critère spatial que si
--     station_if_no_position est vrai et que la station est la même (201 paires au 11 novembre 2026).
-- explore.filet_uvp_compare(...)
--     Une ligne par paire × analyse FILET : abondance FILET (somme des taxons et stades choisis, volume
--     profondeur et volume débitmètre séparés) et abondance UVP sur la couche du trait de filet : objets
--     retenus dans les tranches UVP entièrement comprises dans [min_sample_depth, max_sample_depth], divisés
--     par le volume de toutes ces tranches (tranches sans objet comprises). couverture = épaisseur des
--     tranches / épaisseur de la couche.
--
-- Aucune conversion entre les deux méthodes : les valeurs sont posées côte à côte, le rapport est un
-- simple quotient. Les deux fonctions lisent les vues explore (droits du compte appelant).
-- Additive et relançable (anciennes signatures retirées).
DROP FUNCTION IF EXISTS explore.filet_uvp_pairs(double precision, double precision, boolean);
DO $$ BEGIN  -- version without the UVP position (return type changed)
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'filet_uvp_pairs' AND pronamespace = 'explore'::regnamespace
               AND NOT 'uvp_position_source' = ANY(proargnames)) THEN
        DROP FUNCTION explore.filet_uvp_pairs(double precision, double precision, boolean, boolean);
    END IF;
END $$;
DROP FUNCTION IF EXISTS explore.filet_uvp_compare(double precision, double precision, boolean, text, text, text[], double precision, double precision, text, boolean, boolean);

CREATE OR REPLACE FUNCTION explore.station_norm(p_station text)
RETURNS text LANGUAGE sql IMMUTABLE
AS $$
    -- Same normalization as populate_filet_uvp_matches.py: letters and digits only, upper case, a leading
    -- « G » before a digit dropped (GreenEdge « G107 » = « 107 »).
    SELECT CASE WHEN n ~ '^G[0-9]' THEN substr(n, 2) ELSE n END
    FROM (SELECT upper(regexp_replace(p_station, '[^A-Za-z0-9]', '', 'g')) AS n) s
$$;

CREATE OR REPLACE FUNCTION explore.filet_uvp_pairs(
    p_max_km double precision DEFAULT 30,
    p_max_hours double precision DEFAULT 24,
    p_require_same_station boolean DEFAULT false,
    p_station_if_no_position boolean DEFAULT false)
RETURNS TABLE (filet_sample_ref bigint, filet_sample_id text, filet_station text, filet_sampled_at timestamp,
               filet_latitude double precision, filet_longitude double precision,
               uvp_profile_id bigint, uvp_sample_name text, uvp_station text, uvp_sampled_at timestamp,
               uvp_latitude double precision, uvp_longitude double precision, uvp_position_source text,
               distance_km double precision, time_gap_hours double precision, same_station boolean,
               candidates_for_sample integer, rank_for_sample integer)
LANGUAGE sql STABLE
AS $$
    WITH uvp AS (
        -- Position from EcoPart; when EcoPart has none (GreenEdge 2016), from the profile's EcoTaxa samples.
        SELECT u.uvp_profile_id, min(u.sample_name) AS sample_name, min(u.station_key) AS station_key,
               min(u.sampled_at) AT TIME ZONE 'UTC' AS sampled_at,
               coalesce(avg(u.latitude), avg(e.latitude)) AS latitude,
               coalesce(avg(u.longitude), avg(e.longitude)) AS longitude,
               CASE WHEN avg(u.latitude) IS NOT NULL THEN 'EcoPart'
                    WHEN avg(e.latitude) IS NOT NULL THEN 'EcoTaxa (samples)' END AS position_source
        FROM explore.uvp_samples u
        LEFT JOIN explore.ecotaxa_samples e ON e.ecotaxa_sample_id = u.ecotaxa_sample_id
        GROUP BY u.uvp_profile_id
    ), pairs AS (
        SELECT f.id AS filet_sample_ref, f.sample_id, f.station_name, f.deployment_datetime_start AS f_at,
               f.latitude AS f_lat, f.longitude AS f_lon, u.uvp_profile_id, u.sample_name, u.station_key,
               u.sampled_at AS u_at, u.latitude AS u_lat, u.longitude AS u_lon, u.position_source AS u_src,
               CASE WHEN f.latitude IS NULL OR u.latitude IS NULL THEN NULL ELSE
                   2 * 6371.0088 * asin(sqrt(power(sin(radians(u.latitude - f.latitude) / 2), 2)
                       + cos(radians(f.latitude)) * cos(radians(u.latitude))
                       * power(sin(radians(u.longitude - f.longitude) / 2), 2))) END AS km,
               abs(extract(epoch FROM (u.sampled_at - f.deployment_datetime_start)) / 3600.0) AS hours,
               coalesce(explore.station_norm(f.station_name) = explore.station_norm(u.station_key), false) AS same
        FROM explore.filet_samples f
        JOIN uvp u ON abs(extract(epoch FROM (u.sampled_at - f.deployment_datetime_start)) / 3600.0) <= p_max_hours
        WHERE f.deployment_datetime_start IS NOT NULL
    )
    SELECT filet_sample_ref, sample_id, station_name, f_at, f_lat, f_lon, uvp_profile_id, sample_name, station_key,
           u_at, u_lat, u_lon, u_src, round(km::numeric, 2)::double precision, round(hours::numeric, 2)::double precision, same,
           (count(*) OVER w)::integer,
           (row_number() OVER (w ORDER BY coalesce(km / nullif(p_max_km, 0), 0) + hours / nullif(p_max_hours, 0),
                               uvp_profile_id))::integer
    FROM pairs
    WHERE (p_max_km IS NULL OR km <= p_max_km OR (p_station_if_no_position AND km IS NULL AND same))
      AND (NOT p_require_same_station OR same)
    WINDOW w AS (PARTITION BY filet_sample_ref)
$$;
COMMENT ON FUNCTION explore.filet_uvp_pairs(double precision, double precision, boolean, boolean) IS
    'Paires FILET–UVP candidates : distance (km), écart (h), station identique; max_km NULL = sans critère spatial; station_if_no_position : accepter par la station un profil sans position; rang 1 = le plus proche.';

CREATE OR REPLACE FUNCTION explore.filet_uvp_compare(
    p_max_km double precision DEFAULT 30,
    p_max_hours double precision DEFAULT 24,
    p_require_same_station boolean DEFAULT false,
    p_station_if_no_position boolean DEFAULT false,
    p_uvp_taxon text DEFAULT 'Copepoda',
    p_filet_taxon_pattern text DEFAULT '%',
    p_filet_stages text[] DEFAULT ARRAY['COPEPODID'],
    p_min_size_um double precision DEFAULT NULL,
    p_max_size_um double precision DEFAULT NULL,
    p_size_measure text DEFAULT 'esd',
    p_validated_only boolean DEFAULT true,
    p_best_only boolean DEFAULT true)
RETURNS TABLE (filet_sample_id text, filet_analysis_id text, filet_station text, filet_sampled_at timestamp,
               uvp_profile_id bigint, uvp_sample_name text, distance_km double precision,
               time_gap_hours double precision, same_station boolean, rank_for_sample integer,
               layer_min_m numeric, layer_max_m numeric, net_mesh_size_um numeric,
               filet_n_taxa integer, filet_abundance_depth_ind_m3 numeric, filet_abundance_flowmeter_ind_m3 numeric,
               uvp_n_bins integer, uvp_layer_coverage numeric, uvp_volume_m3 numeric, uvp_n_objects bigint,
               uvp_abundance_ind_m3 numeric, ratio_uvp_filet_depth numeric)
LANGUAGE plpgsql STABLE
AS $$
#variable_conflict use_column
DECLARE
    copepodid text[] := ARRAY['C1','C2','C3','C4','C5','M','F','COP_NS'];
    nauplius text[] := ARRAY['N1','N2','N3','N4','N5','N6','NAUP_NS'];
BEGIN
    -- Aggregate stages are the exact sums of their parts (verified on the 26 May 2026 export): choosing both
    -- would count the same animals twice.
    IF p_filet_stages IS NULL OR cardinality(p_filet_stages) = 0 THEN
        RAISE EXCEPTION 'p_filet_stages : au moins un stade (ex. {COPEPODID}, {C4,C5,M,F}, {ALL_STAGES})';
    END IF;
    IF ('ALL_STAGES' = ANY(p_filet_stages) AND cardinality(p_filet_stages) > 1)
       OR ('COPEPODID' = ANY(p_filet_stages) AND p_filet_stages && copepodid)
       OR ('NAUPLIUS' = ANY(p_filet_stages) AND p_filet_stages && nauplius) THEN
        RAISE EXCEPTION 'p_filet_stages % : un stade agrégé et ses parties comptent deux fois les mêmes individus', p_filet_stages;
    END IF;
    IF p_size_measure NOT IN ('esd', 'major') THEN
        RAISE EXCEPTION 'p_size_measure : esd (diamètre sphérique équivalent) ou major (grand axe)';
    END IF;
    RETURN QUERY
    WITH pairs AS (
        SELECT * FROM explore.filet_uvp_pairs(p_max_km, p_max_hours, p_require_same_station, p_station_if_no_position) p
        WHERE NOT p_best_only OR p.rank_for_sample = 1
    ), filet AS (
        SELECT d.sample_id, d.analysis_id, min(d.min_sample_depth) AS dmin, min(d.max_sample_depth) AS dmax,
               min(d.net_mesh_size) AS mesh, count(DISTINCT d.taxon_id)::integer AS n_taxa,
               sum(d.abundance_depth_ind_m3) AS ab_depth, sum(d.abundance_flowmeter_ind_m3) AS ab_flow
        FROM explore.filet_data d
        WHERE d.metadata_matched AND d.taxon_id ILIKE p_filet_taxon_pattern AND d.stage = ANY(p_filet_stages)
          AND d.sample_id IN (SELECT p.filet_sample_id FROM pairs p)
        GROUP BY d.sample_id, d.analysis_id
    ), bins AS (
        SELECT DISTINCT s.uvp_profile_id, s.uvp_bin_id, s.depth_min_m, s.depth_max_m, s.sampled_volume_l
        FROM explore.uvp_particle_sizes s
        WHERE s.uvp_profile_id IN (SELECT p.uvp_profile_id FROM pairs p)
    ), layer AS (
        SELECT p.*, f.analysis_id, f.dmin, f.dmax, f.mesh, f.n_taxa, f.ab_depth, f.ab_flow
        FROM pairs p JOIN filet f ON f.sample_id = p.filet_sample_id
    ), layer_bins AS (
        SELECT l.filet_sample_id, l.analysis_id, l.uvp_profile_id, b.uvp_bin_id, b.depth_min_m, b.depth_max_m,
               b.sampled_volume_l
        FROM layer l JOIN bins b ON b.uvp_profile_id = l.uvp_profile_id
         AND b.depth_min_m >= l.dmin AND b.depth_max_m <= l.dmax
    ), taxa AS (
        SELECT t.taxon_id::text AS taxon_id FROM explore.ecotaxa_taxa t
        WHERE t.object_class = 'organism' AND p_uvp_taxon = ANY(t.taxon_lineage)
    ), objects AS (
        SELECT lb.filet_sample_id, lb.analysis_id, lb.uvp_profile_id, count(*) AS n
        FROM layer_bins lb
        JOIN explore.uvp_object_sizes o ON o.uvp_bin_id = lb.uvp_bin_id AND o.uvp_profile_id = lb.uvp_profile_id
        WHERE o.taxon_id IN (SELECT taxon_id FROM taxa)
          AND (NOT p_validated_only OR o.annotation_status = 'validated')
          AND (p_min_size_um IS NULL OR (CASE WHEN p_size_measure = 'esd' THEN o.esd_um ELSE o.major_um END) >= p_min_size_um)
          AND (p_max_size_um IS NULL OR (CASE WHEN p_size_measure = 'esd' THEN o.esd_um ELSE o.major_um END) < p_max_size_um)
        GROUP BY 1, 2, 3
    ), uvp AS (
        SELECT lb.filet_sample_id, lb.analysis_id, lb.uvp_profile_id, count(*)::integer AS n_bins,
               sum(lb.depth_max_m - lb.depth_min_m) AS thickness, sum(lb.sampled_volume_l) / 1000.0 AS volume_m3
        FROM layer_bins lb GROUP BY 1, 2, 3
    )
    SELECT l.filet_sample_id, l.analysis_id, l.filet_station, l.filet_sampled_at, l.uvp_profile_id,
           l.uvp_sample_name, l.distance_km, l.time_gap_hours, l.same_station, l.rank_for_sample,
           l.dmin, l.dmax, l.mesh, l.n_taxa, round(l.ab_depth, 4), round(l.ab_flow, 4),
           coalesce(u.n_bins, 0), round((u.thickness / nullif(l.dmax - l.dmin, 0))::numeric, 3),
           round(u.volume_m3::numeric, 3), coalesce(o.n, 0),
           round((coalesce(o.n, 0) / nullif(u.volume_m3, 0))::numeric, 4),
           round(((coalesce(o.n, 0) / nullif(u.volume_m3, 0)) / nullif(l.ab_depth, 0))::numeric, 4)
    FROM layer l
    LEFT JOIN uvp u USING (filet_sample_id, analysis_id, uvp_profile_id)
    LEFT JOIN objects o USING (filet_sample_id, analysis_id, uvp_profile_id)
    ORDER BY l.filet_sampled_at, l.filet_sample_id, l.analysis_id, l.rank_for_sample;
END
$$;
COMMENT ON FUNCTION explore.filet_uvp_compare(double precision, double precision, boolean, boolean, text, text, text[], double precision, double precision, text, boolean, boolean) IS
    'Abondances FILET et UVP sur la même couche (tranches UVP entièrement dans le trait de filet), taxons, stades, taille UVP (esd ou major, µm) et statut choisis; volumes des tranches vides compris.';
