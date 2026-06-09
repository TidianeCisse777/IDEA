"""TDD — résolution des pièces jointes Open WebUI.

On vérifie que le resolver transforme le bloc XML en consigne exploitable
par l'agent, sans dépendre du conteneur Docker dans le test.
"""

from pathlib import Path


def test_resolve_attached_files_copies_file_and_rewrites_prompt(tmp_path):
    from tools.openwebui_uploads import resolve_attached_files

    uploads_dir = tmp_path / "uploads"

    copied = {}

    def fake_copy(container_path: str, local_path: Path) -> None:
        copied["container_path"] = container_path
        copied["local_path"] = str(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("a,b\n1,2\n", encoding="utf-8")

    text = """
Bonjour
<attached_files>
  <file type="file" url="12345" content_type="text/csv" name="stations.csv"/>
</attached_files>
"""

    result = resolve_attached_files(
        text,
        copy_from_container=fake_copy,
        uploads_dir=uploads_dir,
        webui_uploads_path="/app/backend/data/uploads",
        webui_container="open-webui",
    )

    assert "<attached_files>" not in result
    assert "stations.csv" in result
    assert "Charge le fichier avec l'outil load_file" in result
    assert copied["container_path"] == "/app/backend/data/uploads/12345_stations.csv"
    assert copied["local_path"].endswith("uploads/stations.csv")
    assert (uploads_dir / "stations.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"
