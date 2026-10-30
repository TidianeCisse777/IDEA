-- Additive migration: expose the accepted FILET<->UVP taxon correspondence
-- (warehouse.taxon_mapping) that explore.filet_uvp_abundance already joins on
-- internally, so a scoped agent can do the same join itself instead of
-- guessing by taxon name. Scoped reader accounts only ever get USAGE on the
-- explore schema (docs/warehouse_roles.sql), never on warehouse directly, so
-- without this view warehouse.taxon_mapping was unreachable to them.
--
-- taxon_mapping is a reference/catalog table, exempt from row-level security
-- like dataset_version/dataset_metadata (see explore.access_audit's own
-- exemption list) : a mapping entry is not raw occurrence data tied to a
-- contract, zone or year, so nothing here needs scoping.
CREATE OR REPLACE VIEW explore.taxon_mapping AS
SELECT filet_taxon_id, uvp_taxon_id, mapping_relation, mapping_version, evidence
FROM warehouse.taxon_mapping
WHERE mapping_status = 'accepted';

COMMENT ON VIEW explore.taxon_mapping IS
    'Correspondance taxonomique FILET<->UVP retenue (mapping_status=accepted uniquement); c''est la meme jointure que explore.filet_uvp_abundance utilise en interne. '
    'uvp_taxon_id suit la meme convention que uvp_taxon_abundance.taxon_key (ecotaxa:id:..., ecotaxa:name:... ou warehouse:unclassified) : calculer ce taxon_key sur explore.uvp_object_sizes (deja expose) pour joindre ici. '
    'Les correspondances ambiguous ou rejected ne sont pas montrees : un taxon FILET sans ligne ici n''a pas (encore) de correspondance UVP retenue, ce n''est pas la preuve qu''il n''existe aucune proposition.';
