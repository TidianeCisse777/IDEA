-- FAIR migration for the NeoLab warehouse. Additive and idempotent: it never
-- modifies a scientific value, and can be replayed on a deployed database.
-- Apply after warehouse_schema_proposal.sql and warehouse_metadata_migration.sql.
-- Requirements and evidence: docs/WAREHOUSE_FAIR_REQUIREMENTS.md.

-- F2/F4, I3, R1: descriptive fields a repository needs and the catalog lacked.
ALTER TABLE warehouse.dataset_metadata
    ADD COLUMN IF NOT EXISTS keywords_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS related_identifiers_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS license_uri text,
    ADD COLUMN IF NOT EXISTS access_conditions text,
    ADD COLUMN IF NOT EXISTS metadata_standard text,
    ADD COLUMN IF NOT EXISTS access_contract text;

-- I1: a column can point to a community term (unit, variable, vocabulary).
ALTER TABLE warehouse.column_metadata
    ADD COLUMN IF NOT EXISTS vocabulary text,
    ADD COLUMN IF NOT EXISTS standard_uri text;

-- F1: an identifier names one dataset version, never two.
CREATE UNIQUE INDEX IF NOT EXISTS dataset_metadata_persistent_identifier_uidx
    ON warehouse.dataset_metadata (persistent_identifier)
    WHERE persistent_identifier IS NOT NULL;

-- R1: nothing can be marked validated or published without the metadata that
-- makes it reusable. Drafts and retired versions stay unconstrained.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'dataset_metadata_publish_gate'
          AND conrelid = 'warehouse.dataset_metadata'::regclass
    ) THEN
        ALTER TABLE warehouse.dataset_metadata
            ADD CONSTRAINT dataset_metadata_publish_gate CHECK (
                publication_status IN ('draft', 'retired')
                OR (
                    license IS NOT NULL
                    AND jsonb_array_length(creators_json) > 0
                    AND contact_role IS NOT NULL
                    AND methodology IS NOT NULL
                    AND (publication_status <> 'published' OR persistent_identifier IS NOT NULL)
                )
            );
    END IF;
END
$$;

-- F2/A2: the catalog stays readable whatever the access level of the data, and
-- keeps retired versions. It exposes no file location, only the file count.
CREATE OR REPLACE VIEW explore.dataset_catalog AS
SELECT
    v.id AS dataset_version_id,
    v.source_instance,
    v.dataset_key,
    v.version_key,
    v.sha256,
    m.title,
    m.description,
    m.creators_json,
    m.keywords_json,
    m.persistent_identifier,
    m.license,
    m.license_uri,
    m.access_level,
    m.access_conditions,
    m.publication_status,
    m.temporal_start,
    m.temporal_end,
    m.spatial_extent_json,
    m.taxonomic_scope,
    m.methodology,
    m.software_version,
    m.schema_version,
    m.metadata_standard,
    m.related_identifiers_json,
    (SELECT count(*) FROM warehouse.dataset_file f
      WHERE f.dataset_version_id = v.id) AS file_count,
    m.access_contract
FROM warehouse.dataset_version v
LEFT JOIN warehouse.dataset_metadata m ON m.dataset_version_id = v.id;

-- Per-criterion readiness. A criterion is true only when the catalog proves it;
-- the view measures metadata completeness, not scientific validity.
CREATE OR REPLACE VIEW explore.fair_readiness AS
WITH checks AS (
    SELECT
        c.dataset_version_id,
        c.source_instance,
        c.dataset_key,
        c.version_key,
        c.persistent_identifier IS NOT NULL AS f1_persistent_identifier,
        coalesce(c.title, '') <> ''
            AND coalesce(c.description, '') <> ''
            AND jsonb_array_length(coalesce(c.creators_json, '[]'::jsonb)) > 0
            AND coalesce((m.metadata_json ->> 'description_pending')::boolean, false) = false
            AS f2_rich_metadata,
        jsonb_array_length(coalesce(c.keywords_json, '[]'::jsonb)) > 0 AS f4_searchable,
        c.access_level IS NOT NULL
            AND (c.access_level = 'open' OR c.access_conditions IS NOT NULL) AS a1_access_declared,
        c.metadata_standard IS NOT NULL AS i1_standard_declared,
        jsonb_array_length(coalesce(c.related_identifiers_json, '[]'::jsonb)) > 0 AS i3_related_references,
        c.license IS NOT NULL AS r1_license,
        c.methodology IS NOT NULL
            AND c.software_version IS NOT NULL
            AND c.file_count > 0 AS r2_provenance,
        EXISTS (
            SELECT 1 FROM warehouse.validation_run r
            WHERE r.dataset_version_id = c.dataset_version_id AND r.status = 'passed'
        ) AS r3_validated
    FROM explore.dataset_catalog c
    LEFT JOIN warehouse.dataset_metadata m ON m.dataset_version_id = c.dataset_version_id
)
SELECT
    checks.*,
    array_remove(ARRAY[
        CASE WHEN NOT f1_persistent_identifier THEN 'F1' END,
        CASE WHEN NOT f2_rich_metadata THEN 'F2' END,
        CASE WHEN NOT f4_searchable THEN 'F4' END,
        CASE WHEN NOT a1_access_declared THEN 'A1' END,
        CASE WHEN NOT i1_standard_declared THEN 'I1' END,
        CASE WHEN NOT i3_related_references THEN 'I3' END,
        CASE WHEN NOT r1_license THEN 'R1' END,
        CASE WHEN NOT r2_provenance THEN 'R2' END,
        CASE WHEN NOT r3_validated THEN 'R3' END
    ], NULL) AS missing_criteria,
    (f1_persistent_identifier AND f2_rich_metadata AND f4_searchable
        AND a1_access_declared AND i1_standard_declared AND i3_related_references
        AND r1_license AND r2_provenance AND r3_validated) AS fair_ready
FROM checks;

-- I1/R: how much of the real schema is described in column_metadata. A column
-- counts as documented when any row (global or per version) describes it.
CREATE OR REPLACE VIEW explore.fair_column_coverage AS
SELECT
    c.relname::text AS table_name,
    count(*) AS column_count,
    count(*) FILTER (WHERE d.column_name IS NOT NULL) AS documented_count,
    count(*) FILTER (WHERE d.has_unit) AS with_unit_count,
    count(*) FILTER (WHERE d.has_standard_uri) AS with_standard_uri_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
LEFT JOIN (
    SELECT table_name, column_name,
           bool_or(unit IS NOT NULL) AS has_unit,
           bool_or(standard_uri IS NOT NULL) AS has_standard_uri
    FROM warehouse.column_metadata
    WHERE schema_name = 'warehouse'
    GROUP BY table_name, column_name
) d ON d.table_name = c.relname::text AND d.column_name = a.attname::text
WHERE n.nspname = 'warehouse' AND c.relkind = 'r'
GROUP BY c.relname;

COMMENT ON VIEW explore.dataset_catalog IS
    'Catalogue des versions de jeux de données: identifiant, licence, accès, couverture et provenance. Une ligne par version, y compris retirée. Lecture libre même quand les données sont restreintes.';
COMMENT ON VIEW explore.fair_readiness IS
    'Complétude FAIR des métadonnées par version (F1 F2 F4 A1 I1 I3 R1 R2 R3). Mesure le catalogue, pas la validité scientifique; missing_criteria liste ce qui manque.';
COMMENT ON VIEW explore.fair_column_coverage IS
    'Part des colonnes du schéma warehouse décrites dans column_metadata, avec unité et URI de terme standard. Une ligne par table.';
