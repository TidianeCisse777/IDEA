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


def test_resolve_attached_files_marks_images_without_load_file_instruction(tmp_path):
    from tools.openwebui_uploads import resolve_attached_files

    uploads_dir = tmp_path / "uploads"

    def fake_copy(container_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(b"png-bytes")

    text = """
Bonjour
<attached_files>
  <file type="file" url="abcde" content_type="image/png" name="figure.png"/>
</attached_files>
"""

    result = resolve_attached_files(
        text,
        copy_from_container=fake_copy,
        uploads_dir=uploads_dir,
        webui_uploads_path="/app/backend/data/uploads",
        webui_container="open-webui",
    )

    assert "Image(s) chargée(s) depuis Open WebUI" in result
    assert "load_file" not in result
    assert (uploads_dir / "figure.png").exists()


# --- resolve_request_files : format JSON OpenWebUI 0.9.x ---


def test_resolve_request_files_csv_returns_load_file_instruction(tmp_path):
    """Un fichier CSV dans req.files doit produire une consigne load_file."""
    from tools.openwebui_uploads import resolve_request_files

    uploads_dir = tmp_path / "uploads"
    copied = {}

    def fake_copy(container_path: str, local_path: Path) -> None:
        copied["container_path"] = container_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("station,depth\nA,10\nB,20\n", encoding="utf-8")

    files = [
        {
            "type": "file",
            "file": {
                "id": "abc-123",
                "filename": "stations.csv",
                "meta": {"name": "stations.csv", "content_type": "text/csv"},
            },
        }
    ]

    text, image_parts = resolve_request_files(
        files,
        copy_from_container=fake_copy,
        uploads_dir=uploads_dir,
    )

    assert "stations.csv" in text
    assert "load_file" in text
    assert image_parts == []
    assert copied["container_path"] == "/app/backend/data/uploads/abc-123_stations.csv"
    assert (uploads_dir / "stations.csv").read_text(encoding="utf-8") == "station,depth\nA,10\nB,20\n"


def test_resolve_request_files_none_returns_empty(tmp_path):
    from tools.openwebui_uploads import resolve_request_files

    assert resolve_request_files(None) == ("", [])
    assert resolve_request_files([]) == ("", [])


def test_resolve_request_files_image_returns_base64_data_url(tmp_path):
    """Une image uploadée doit produire un bloc `image_url` data:base64, pas du texte.

    Régression : avant, le code mettait juste un chemin local dans le texte, le LLM
    ne voyait rien. L'image doit être encodée en data URL pour être visible côté API.
    """
    import base64

    from tools.openwebui_uploads import resolve_request_files

    uploads_dir = tmp_path / "uploads"
    # 1×1 PNG transparent valide
    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )

    def fake_copy(container_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(png_bytes)

    files = [
        {
            "type": "file",
            "file": {
                "id": "img-1",
                "filename": "shot.png",
                "meta": {"content_type": "image/png"},
            },
        }
    ]

    text, image_parts = resolve_request_files(
        files,
        copy_from_container=fake_copy,
        uploads_dir=uploads_dir,
    )

    assert len(image_parts) == 1
    part = image_parts[0]
    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    # le base64 dans l'URL doit décoder vers les bytes PNG d'origine
    decoded = base64.b64decode(url.split(",", 1)[1])
    assert decoded == png_bytes
    # texte mentionne le nom, mais sans consigne load_file (pas tabulaire)
    assert "shot.png" in text
    assert "load_file" not in text


def test_resolve_request_files_image_plus_csv_keeps_both(tmp_path):
    """Mixte image + CSV : image dans image_parts, CSV dans le texte load_file."""
    import base64

    from tools.openwebui_uploads import resolve_request_files

    uploads_dir = tmp_path / "uploads"
    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )

    def fake_copy(container_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.suffix == ".png":
            local_path.write_bytes(png_bytes)
        else:
            local_path.write_text("a,b\n1,2\n", encoding="utf-8")

    files = [
        {"type": "file", "file": {"id": "1", "filename": "shot.png",
                                    "meta": {"content_type": "image/png"}}},
        {"type": "file", "file": {"id": "2", "filename": "data.csv",
                                    "meta": {"content_type": "text/csv"}}},
    ]

    text, image_parts = resolve_request_files(
        files, copy_from_container=fake_copy, uploads_dir=uploads_dir,
    )

    assert len(image_parts) == 1
    assert "data.csv" in text
    assert "load_file" in text
    assert "shot.png" in text


def test_default_webui_container_matches_docker_compose():
    """Le default doit correspondre à container_name: dans docker-compose.yml.

    Régression : le default `open-webui` (tiret) ne matchait pas le container réel
    `open_webui` (underscore), tous les `docker exec` échouaient silencieusement et
    l'agent ne voyait jamais les fichiers uploadés.
    """
    import re as _re
    from pathlib import Path as _Path

    from tools.openwebui_uploads import DEFAULT_WEBUI_CONTAINER

    compose = (_Path(__file__).parent.parent / "docker-compose.yml").read_text()
    # Cible le bloc du service open-webui (image openwebui/open-webui), pas un autre service.
    match = _re.search(
        r"image:\s*openwebui/open-webui\S*\s*\n\s*container_name:\s*(\S+)",
        compose,
    )
    assert match, "bloc open-webui (image + container_name) introuvable dans docker-compose.yml"
    assert DEFAULT_WEBUI_CONTAINER == match.group(1), (
        f"DEFAULT_WEBUI_CONTAINER={DEFAULT_WEBUI_CONTAINER!r} ne matche pas "
        f"container_name={match.group(1)!r}. docker exec va échouer silencieusement "
        "et les uploads ne seront jamais visibles par l'agent."
    )
