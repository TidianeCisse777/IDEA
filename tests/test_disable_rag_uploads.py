import tempfile
import unittest
from pathlib import Path

from openwebui.disable_rag_uploads import (
    BACKEND_MARKER,
    MARKER,
    patch_upload_api,
    patch_upload_backend,
)


SOURCE = """export const uploadFile = async (metadata, process, stream) => {
\tconst data = new FormData();
\tif (metadata) {
\t\tdata.append('metadata', JSON.stringify(metadata));
\t}
\treturn { process, stream };
};
"""
BACKEND_SOURCE = """async def upload_file_handler(file, process, process_in_background):
    log.info('file.content_type: %s %s', file.content_type, process)
    if process:
        process_uploaded_file(file)
"""


class DisableRagUploadsTests(unittest.TestCase):
    def test_patch_forces_storage_only_upload_and_skips_status_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.ts"
            path.write_text(SOURCE, encoding="utf-8")

            patch_upload_api(path)

            patched = path.read_text(encoding="utf-8")
            self.assertIn(MARKER, patched)
            self.assertIn("\tprocess = false;", patched)
            self.assertIn("\tstream = false;", patched)

    def test_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.ts"
            path.write_text(SOURCE, encoding="utf-8")

            patch_upload_api(path)
            once = path.read_text(encoding="utf-8")
            patch_upload_api(path)

            self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_backend_policy_overrides_clients_that_still_request_rag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "files.py"
            path.write_text(BACKEND_SOURCE, encoding="utf-8")

            patch_upload_backend(path)

            patched = path.read_text(encoding="utf-8")
            self.assertIn(BACKEND_MARKER, patched)
            self.assertLess(patched.index("process = False"), patched.index("if process:"))
            self.assertIn("process_in_background = False", patched)


if __name__ == "__main__":
    unittest.main()
