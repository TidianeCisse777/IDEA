"""Cache persistant de TSV EcoPart."""

from __future__ import annotations

import pytest


def _write_ecopart_tsv(path, *, profile: str = "RA62", volume: float = 101.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Profile\tDepth [m]\tSampled volume [L]\n"
        f"{profile}\t42.5\t{volume}\n",
        encoding="utf-8",
    )
    return path


def test_import_ecopart_tsv_deduplicates_content_and_records_profiles(
    tmp_path, monkeypatch
):
    from core.ecopart_cache import import_ecopart_tsv

    monkeypatch.setenv("ECOPART_CACHE_DIR", str(tmp_path / "cache"))
    source = _write_ecopart_tsv(tmp_path / "part.tsv")

    first = import_ecopart_tsv(source, provenance="local_import")
    second = import_ecopart_tsv(source, provenance="local_import")

    assert first.content_sha256 == second.content_sha256
    assert first.path.exists()
    assert first.path.parent.name == "files"
    assert first.profiles == ("RA62",)
    assert len(list((tmp_path / "cache" / "files").glob("*.tsv"))) == 1


def test_invalid_tsv_leaves_no_cache_artifact(tmp_path, monkeypatch):
    from core.ecopart_cache import import_ecopart_tsv

    monkeypatch.setenv("ECOPART_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "bad.tsv"
    source.write_text("Profile\tDepth [m]\nRA62\t42.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sampled volume"):
        import_ecopart_tsv(source, provenance="local_import")

    assert not (tmp_path / "cache" / "manifest.sqlite").exists()


def test_resolution_round_trip_expires(tmp_path, monkeypatch):
    from core.ecopart_cache import load_resolution, save_resolution

    monkeypatch.setenv("ECOPART_CACHE_DIR", str(tmp_path / "cache"))
    save_resolution(
        17498,
        ecopart_project_id=1063,
        resolution="filt_proj",
        status="resolved",
        ttl_seconds=60,
    )

    fresh = load_resolution(17498)
    expired = load_resolution(17498, now=fresh.expires_at + 1)

    assert fresh.ecopart_project_id == 1063
    assert expired is None
