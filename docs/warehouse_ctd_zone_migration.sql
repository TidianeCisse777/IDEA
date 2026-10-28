-- Marine zone on CTD profiles, same columns and convention as EcoTaxa, UVP and
-- FILET. Additive and idempotent; values are filled from the profile
-- coordinates by scripts/assign_filet_zones.py --table ctd_profile, never guessed.
ALTER TABLE warehouse.ctd_profile
    ADD COLUMN IF NOT EXISTS marine_zone_key text,
    ADD COLUMN IF NOT EXISTS marine_zone_name text,
    ADD COLUMN IF NOT EXISTS marine_zone_source text,
    ADD COLUMN IF NOT EXISTS marine_zone_version text,
    ADD COLUMN IF NOT EXISTS marine_zone_assignment_status text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ctd_profile_zone_status_check') THEN
        ALTER TABLE warehouse.ctd_profile ADD CONSTRAINT ctd_profile_zone_status_check
            CHECK (marine_zone_assignment_status IN ('assigned', 'ambiguous', 'outside', 'unresolved'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ctd_profile_zone_idx
    ON warehouse.ctd_profile (marine_zone_key, marine_zone_assignment_status);
