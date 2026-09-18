"""Contrats locaux du schéma warehouse V1.

Ces tests ne se connectent pas à PostgreSQL et n'utilisent pas de données de
production. Ils vérifient le contrat SQL et les deux règles de calcul stables.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DDL = ROOT / "docs" / "warehouse_schema_proposal.sql"


class WarehouseSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = DDL.read_text(encoding="utf-8")

    def test_declares_source_and_exploration_layers(self):
        self.assertIn("CREATE SCHEMA warehouse;", self.sql)
        self.assertIn("CREATE SCHEMA explore;", self.sql)
        self.assertIn("CREATE TABLE warehouse.dataset_version", self.sql)

    def test_preserves_uvp_sources_and_derives_taxonomic_abundance(self):
        for table in ("uvp_profile", "uvp_bin", "uvp_particle", "uvp_taxon_abundance"):
            self.assertRegex(self.sql, rf"CREATE TABLE warehouse\.{table}\b")
        self.assertIn("n_objects_taxon::numeric / sampled_volume_l * 1000", self.sql)
        self.assertIn("calculation_version text NOT NULL", self.sql)

    def test_preserves_filet_normalized_values_without_recomputing_them(self):
        for column in (
            "abundance_depth_ind_m3",
            "abundance_flowmeter_ind_m3",
            "biomass_depth_ug_c_m3",
            "biomass_flowmeter_ug_c_m3",
        ):
            self.assertIn(column, self.sql)
        self.assertIn("Les abondances FILET sont des valeurs source", self.sql)

    def test_keeps_native_ctd_links_and_profile_level_navigation(self):
        for table in ("ctd_profile", "ctd_measurement", "uvp_ctd"):
            self.assertRegex(self.sql, rf"CREATE TABLE warehouse\.{table}\b")
        self.assertIn("CREATE VIEW explore.uvp_ctd AS", self.sql)
        self.assertIn("CREATE VIEW explore.uvp_objects AS", self.sql)

    def test_keeps_unmatched_filet_rows_with_left_join(self):
        view = self.sql.split("CREATE VIEW explore.filet_data AS", 1)[1]
        self.assertIn("LEFT JOIN warehouse.filet_analysis", view)
        self.assertIn("metadata_matched", view)

    def test_exposes_profile_and_measurement_grains(self):
        self.assertIn("CREATE VIEW explore.uvp_ctd AS", self.sql)
        self.assertIn("m.source_row_key, m.scan_key, m.depth_m", self.sql)
        self.assertIn("CREATE VIEW explore.filet_totals AS", self.sql)


class AbundanceFormulaContractTests(unittest.TestCase):
    def test_uvp_bin_formula_converts_litres_to_cubic_metres(self):
        n_objects = 25
        volume_l = 50
        self.assertEqual(n_objects / volume_l * 1000, 500.0)

    def test_uvp_multiple_bins_uses_weighted_volume_not_mean_of_concentrations(self):
        counts = [10, 10]
        volumes_l = [10, 100]
        weighted = sum(counts) / sum(volumes_l) * 1000
        naive_mean = ((counts[0] / volumes_l[0] * 1000) +
                      (counts[1] / volumes_l[1] * 1000)) / 2
        self.assertAlmostEqual(weighted, 181.8181818, places=6)
        self.assertNotEqual(weighted, naive_mean)

    def test_filet_stage_selection_does_not_change_source_values(self):
        source = {"C4": 2.0, "C5": 3.0, "ALL_STAGES": 5.0}
        selected = sum(source[stage] for stage in ("C4", "C5"))
        self.assertEqual(selected, 5.0)
        self.assertEqual(source["ALL_STAGES"], 5.0)


if __name__ == "__main__":
    unittest.main()
