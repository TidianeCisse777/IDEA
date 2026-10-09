-- Additive metadata catalog for the NeoLab warehouse.
-- This catalog describes datasets, source files, columns and validation runs.
-- It never replaces scientific values in the source tables.

CREATE TABLE IF NOT EXISTS warehouse.dataset_metadata (
    dataset_version_id bigint PRIMARY KEY
        REFERENCES warehouse.dataset_version ON DELETE RESTRICT,
    title text NOT NULL,
    description text NOT NULL,
    creators_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    contact_role text,
    source_method text,
    temporal_start timestamptz,
    temporal_end timestamptz,
    spatial_extent_json jsonb,
    taxonomic_scope text,
    methodology text,
    software_version text,
    schema_version text NOT NULL DEFAULT 'warehouse-v1',
    persistent_identifier text,
    license text,
    access_level text NOT NULL DEFAULT 'internal'
        CHECK (access_level IN ('private', 'internal', 'restricted', 'open')),
    publication_status text NOT NULL DEFAULT 'draft'
        CHECK (publication_status IN ('draft', 'validated', 'published', 'retired')),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (temporal_end IS NULL OR temporal_start IS NULL OR temporal_end >= temporal_start)
);

CREATE TABLE IF NOT EXISTS warehouse.dataset_file (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL
        REFERENCES warehouse.dataset_version ON DELETE RESTRICT,
    logical_name text NOT NULL,
    source_uri text NOT NULL,
    media_type text,
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    sha256 text NOT NULL,
    retrieved_at timestamptz,
    source_role text NOT NULL DEFAULT 'source'
        CHECK (source_role IN ('source', 'manifest', 'documentation', 'validation', 'derived')),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (dataset_version_id, logical_name, sha256)
);

CREATE TABLE IF NOT EXISTS warehouse.column_metadata (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint REFERENCES warehouse.dataset_version ON DELETE RESTRICT,
    schema_name text NOT NULL DEFAULT 'warehouse',
    table_name text NOT NULL,
    column_name text NOT NULL,
    canonical_name text,
    source_column_name text,
    definition text NOT NULL,
    unit text,
    data_type text NOT NULL,
    missing_value_policy text,
    value_domain_json jsonb,
    provenance_kind text NOT NULL DEFAULT 'source'
        CHECK (provenance_kind IN ('source', 'copied', 'derived', 'quality_control', 'administrative')),
    transformation text,
    metadata_version text NOT NULL DEFAULT '1',
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS column_metadata_lookup_idx
    ON warehouse.column_metadata (dataset_version_id, schema_name, table_name, column_name);

CREATE TABLE IF NOT EXISTS warehouse.validation_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL
        REFERENCES warehouse.dataset_version ON DELETE RESTRICT,
    validator_name text NOT NULL,
    validator_version text,
    code_commit text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL
        CHECK (status IN ('pending', 'passed', 'failed', 'partial')),
    report_uri text,
    summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS validation_run_dataset_idx
    ON warehouse.validation_run (dataset_version_id, started_at DESC);

-- Seed only facts already present in dataset_version. Scientific descriptions,
-- creators, licence and access decisions remain explicit TODOs for curation.
INSERT INTO warehouse.dataset_metadata (
    dataset_version_id, title, description, source_method,
    schema_version, access_level, publication_status, metadata_json
)
SELECT
    v.id,
    format('%s dataset %s (%s)', v.source_instance, v.dataset_key, v.version_key),
    format('Version %s/%s enregistree dans le warehouse; description scientifique a completer.', v.source_instance, v.dataset_key),
    v.source_instance,
    'warehouse-v1',
    'internal',
    'draft',
    jsonb_build_object('seeded_from', 'warehouse.dataset_version', 'description_pending', true)
FROM warehouse.dataset_version v
ON CONFLICT (dataset_version_id) DO NOTHING;

INSERT INTO warehouse.dataset_file (
    dataset_version_id, logical_name, source_uri, sha256, source_role, metadata_json
)
SELECT
    v.id,
    format('%s/%s/%s', v.source_instance, v.dataset_key, v.version_key),
    v.file_manifest_uri,
    v.sha256,
    CASE WHEN v.source_instance = 'derived' THEN 'derived' ELSE 'source' END,
    jsonb_build_object('seeded_from', 'warehouse.dataset_version')
FROM warehouse.dataset_version v
ON CONFLICT (dataset_version_id, logical_name, sha256) DO NOTHING;
