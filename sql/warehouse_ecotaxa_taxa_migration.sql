-- Additive migration: EcoTaxa taxonomy (lineage) and object counts per sample
-- and taxon, so that an agent can find a taxon and count it without scanning the
-- 15 M objects.
--
-- Found live (7 novembre 2026, traces of 103 agent cases): searching a taxon by
-- name in explore.ecotaxa_objects (taxon_name ILIKE '%oith%' on project 10101)
-- took 31.8 s under row security, beyond the 30 s limit: 10 agent queries were
-- cancelled. And "how many copepods" had no answer in the data: the warehouse held
-- the category name only, not its place in the tree, so the agent listed
-- Calanoida, Metridia... from memory.
--
-- ecotaxa_taxon: one EcoTaxa category per row, with its lineage from itself up to
-- the root (EcoTaxa /taxon_set/query, public), filled by
-- scripts/populate_ecotaxa_taxonomy.py. A reference table, like marine_zone: the
-- tree carries no project data, so no row security.
-- ecotaxa_sample_taxon: object counts per sample, category and annotation status,
-- recomputed from warehouse.ecotaxa_object by warehouse.refresh_ecotaxa_sample_taxon()
-- for every sample whose totals no longer match its counters (all samples on the
-- first run: 1.4 s for 15 M objects). Its rows are visible through the sample's
-- row security (warehouse_access_control.sql).

CREATE TABLE IF NOT EXISTS warehouse.ecotaxa_taxon (
    taxon_id integer PRIMARY KEY,
    taxon_name text NOT NULL,
    display_name text,
    taxon_type text,
    taxon_status text,
    taxon_rank text,
    aphia_id integer,
    lineage text[] NOT NULL,
    id_lineage integer[] NOT NULL,
    source_uri text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
-- What an object of this category is, from the root of its EcoTaxa lineage. Found
-- live (7 novembre 2026): asked for "the vertical profile of the project", an agent
-- plotted the abundance of all categories of project 10101 as "ind/m3"; 97 % of
-- those objects were detritus<not-living, and its 675 m peak was detritus.
-- organism: under Biota; not_living: detritus, artefacts, feces; technical: Biota
-- categories that are segmentation or duplicate flags; temporary: EcoTaxa t0xx.
ALTER TABLE warehouse.ecotaxa_taxon ADD COLUMN IF NOT EXISTS object_class text GENERATED ALWAYS AS (
    CASE
        WHEN lineage[cardinality(lineage)] = 'not-living' THEN 'not_living'
        WHEN lineage[cardinality(lineage)] = 'temporary' THEN 'temporary'
        WHEN lineage[cardinality(lineage)] = 'Biota'
             AND lineage[cardinality(lineage) - 1] IN ('badsegmentation', 'oversegmented', 'duplicate') THEN 'technical'
        WHEN lineage[cardinality(lineage)] = 'Biota' THEN 'organism'
        ELSE 'unknown'
    END) STORED;
CREATE INDEX IF NOT EXISTS ecotaxa_taxon_id_lineage_idx ON warehouse.ecotaxa_taxon USING gin (id_lineage);
CREATE INDEX IF NOT EXISTS ecotaxa_taxon_lineage_idx ON warehouse.ecotaxa_taxon USING gin (lineage);
COMMENT ON TABLE warehouse.ecotaxa_taxon IS
    'Taxonomie EcoTaxa des catégories présentes dans le warehouse : lignée du taxon jusqu''à la racine (lineage, id_lineage, le taxon en premier), type P (phylogénétique) ou M (morphologique : stade, vue, taille, part, dead, eggs, like...), rang, AphiaID WoRMS. Source : EcoTaxa /taxon_set/query (source_uri), chargée par scripts/populate_ecotaxa_taxonomy.py.';

CREATE TABLE IF NOT EXISTS warehouse.ecotaxa_sample_taxon (
    sample_id bigint NOT NULL REFERENCES warehouse.ecotaxa_sample (id) ON DELETE CASCADE,
    taxon_id integer,
    taxon_name text,
    n_objects bigint NOT NULL,
    n_validated bigint NOT NULL,
    n_predicted bigint NOT NULL,
    n_dubious bigint NOT NULL,
    n_unclassified bigint NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (sample_id, taxon_id)
);
CREATE INDEX IF NOT EXISTS ecotaxa_sample_taxon_taxon_idx ON warehouse.ecotaxa_sample_taxon (taxon_id);
COMMENT ON TABLE warehouse.ecotaxa_sample_taxon IS
    'Nombre d''objets EcoTaxa par sample et catégorie, par statut d''annotation, recalculé depuis warehouse.ecotaxa_object (warehouse.refresh_ecotaxa_sample_taxon). taxon_id NULL = objets jamais classés.';

-- Recompute the samples whose per-taxon totals differ from their counters (or all
-- of them with p_all). Returns the number of samples recomputed.
CREATE OR REPLACE FUNCTION warehouse.refresh_ecotaxa_sample_taxon(p_all boolean DEFAULT false)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    stale bigint[];
BEGIN
    SELECT coalesce(array_agg(s.id), '{}') INTO stale
    FROM warehouse.ecotaxa_sample s
    LEFT JOIN (SELECT sample_id, sum(n_objects) AS n, sum(n_validated) AS v, sum(n_predicted) AS p,
                      sum(n_dubious) AS d, sum(n_unclassified) AS u
               FROM warehouse.ecotaxa_sample_taxon GROUP BY sample_id) t ON t.sample_id = s.id
    WHERE p_all
       OR coalesce(t.n, 0) IS DISTINCT FROM coalesce(s.object_count, 0)
       OR coalesce(t.v, 0) IS DISTINCT FROM coalesce(s.nb_validated, 0)
       OR coalesce(t.p, 0) IS DISTINCT FROM coalesce(s.nb_predicted, 0)
       OR coalesce(t.d, 0) IS DISTINCT FROM coalesce(s.nb_dubious, 0)
       OR coalesce(t.u, 0) IS DISTINCT FROM coalesce(s.nb_unclassified, 0);
    IF cardinality(stale) = 0 THEN
        RETURN 0;
    END IF;
    DELETE FROM warehouse.ecotaxa_sample_taxon WHERE sample_id = ANY (stale);
    INSERT INTO warehouse.ecotaxa_sample_taxon
        (sample_id, taxon_id, taxon_name, n_objects, n_validated, n_predicted, n_dubious, n_unclassified)
    SELECT o.sample_id, o.category_id::integer, max(o.category_name), count(*),
           count(*) FILTER (WHERE o.annotation_status = 'validated'),
           count(*) FILTER (WHERE o.annotation_status = 'predicted'),
           count(*) FILTER (WHERE o.annotation_status = 'dubious'),
           count(*) FILTER (WHERE o.annotation_status IS NULL)
    FROM warehouse.ecotaxa_object o
    WHERE o.sample_id = ANY (stale)
    GROUP BY o.sample_id, o.category_id;
    RETURN cardinality(stale);
END
$$;

SELECT warehouse.refresh_ecotaxa_sample_taxon();

-- Objects of some taxa within given samples (comparisons FILET–UVP, questions by taxon): without this index
-- every object of the samples is read (12,6 s for Calanus in 187 UVP profiles, 11 November 2026).
-- About one to a few minutes to build once on 15 million objects.
CREATE INDEX IF NOT EXISTS ecotaxa_object_sample_category_idx ON warehouse.ecotaxa_object (sample_id, category_id);
