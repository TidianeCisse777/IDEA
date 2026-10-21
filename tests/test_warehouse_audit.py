"""Contrat du diagnostic warehouse, sans serveur ni credentials."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_warehouse.py"
spec = importlib.util.spec_from_file_location("warehouse_audit", PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class WarehouseAuditTests(unittest.TestCase):
    def test_missing_reader_credentials_never_fall_back_to_owner(self):
        with patch.dict(audit.os.environ, {"WAREHOUSE_POSTGRES_PASSWORD": "owner-secret"}, clear=True):
            with self.assertRaisesRegex(ValueError, "WAREHOUSE_READER_PASSWORD"):
                audit.connection_options()

    def test_connection_is_bounded_and_read_only(self):
        with patch.dict(audit.os.environ, {"WAREHOUSE_READER_PASSWORD": "test"}, clear=True):
            options = audit.connection_options()
        self.assertEqual(options["user"], "warehouse_reader")
        self.assertEqual(options["connect_timeout"], 5)
        self.assertIn("default_transaction_read_only=on", options["options"])
        self.assertIn("statement_timeout=30000", options["options"])

    def test_discovery_runs_before_optional_scientific_scan(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        report = audit.inspect(conn)
        self.assertEqual(report["qualification"], "not_requested")
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse(any("FROM explore.uvp_objects" in sql for sql in statements))

    def test_missing_surface_is_explicit_and_not_zero(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        report = audit.inspect(conn, qualify=True)
        self.assertEqual(report["qualification"], "unavailable")
        self.assertIn("explore.uvp_objects", report["missing_views"])
        self.assertNotIn("uvp_taxonomy", report)

    def test_taxonomy_scan_separates_missing_labels_and_annotation(self):
        sql = audit.UVP_TAXONOMY_SQL
        for column in ("dataset_version_id", "taxon_id", "taxon_name", "annotation_status"):
            self.assertIn(column, sql)
        self.assertIn("btrim", sql)
        self.assertIn("COUNT(DISTINCT ecotaxa_object_id)", sql)
        self.assertNotIn("COALESCE(taxon_id", sql)

    def test_qualification_preserves_measured_counts_and_source_versions(self):
        conn = MagicMock()
        uvp = [{"dataset_version_id": 12, "objects": 5, "missing_taxon_name": 2}]
        filet = [{"dataset_version_id": 19, "source_stage_rows": 8}]
        conn.execute.return_value.fetchall.side_effect = [
            [{"table_name": "uvp_objects"}, {"table_name": "filet_data"}],
            uvp, filet,
        ]
        report = audit.inspect(conn, qualify=True)
        self.assertEqual(report["qualification"], "measured")
        self.assertEqual(report["uvp_taxonomy"], uvp)
        self.assertEqual(report["filet_taxonomy"], filet)


if __name__ == "__main__":
    unittest.main()
