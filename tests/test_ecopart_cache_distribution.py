from pathlib import Path
import json

import pytest


def test_ecopart_cache_bundle_round_trip_keeps_manifest_and_tsvs(tmp_path):
    from core.ecopart_cache_distribution import build_cache_bundle, install_cache_bundle

    source = tmp_path / "source"
    (source / "files").mkdir(parents=True)
    (source / "manifest.sqlite").write_bytes(b"sqlite-cache")
    (source / "files" / "abc.tsv").write_text("Profile\tDepth [m]\tSampled volume [L]\nRA62\t2.5\t1\n")

    manifest, archive = build_cache_bundle(source, tmp_path / "release")
    destination = tmp_path / "clone" / "ecopart_cache"
    install_cache_bundle(manifest.read_bytes(), archive.read_bytes(), destination)

    assert (destination / "manifest.sqlite").read_bytes() == b"sqlite-cache"
    assert (destination / "files" / "abc.tsv").exists()


def test_tampered_bundle_preserves_existing_cache(tmp_path):
    from core.ecopart_cache_distribution import (
        CacheBundleValidationError,
        build_cache_bundle,
        install_cache_bundle,
    )

    source = tmp_path / "source"
    (source / "files").mkdir(parents=True)
    (source / "manifest.sqlite").write_bytes(b"new-cache")
    (source / "files" / "abc.tsv").write_text("Profile\tDepth [m]\tSampled volume [L]\nRA62\t2.5\t1\n")
    manifest, archive = build_cache_bundle(source, tmp_path / "release")

    destination = tmp_path / "clone" / "ecopart_cache"
    destination.mkdir(parents=True)
    (destination / "manifest.sqlite").write_bytes(b"old-cache")
    tampered_archive = archive.read_bytes() + b"tampered"

    with pytest.raises(CacheBundleValidationError):
        install_cache_bundle(manifest.read_bytes(), tampered_archive, destination)

    assert (destination / "manifest.sqlite").read_bytes() == b"old-cache"


def test_valid_bundle_replaces_instead_of_merging_existing_cache(tmp_path):
    from core.ecopart_cache_distribution import build_cache_bundle, install_cache_bundle

    source = tmp_path / "source"
    (source / "files").mkdir(parents=True)
    (source / "manifest.sqlite").write_bytes(b"new-cache")
    (source / "files" / "abc.tsv").write_text("Profile\tDepth [m]\tSampled volume [L]\nRA62\t2.5\t1\n")
    manifest, archive = build_cache_bundle(source, tmp_path / "release")

    destination = tmp_path / "clone" / "ecopart_cache"
    destination.mkdir(parents=True)
    (destination / "manifest.sqlite").write_bytes(b"old-cache")
    (destination / "obsolete.tsv").write_text("obsolete")

    install_cache_bundle(manifest.read_bytes(), archive.read_bytes(), destination)

    assert (destination / "manifest.sqlite").read_bytes() == b"new-cache"
    assert not (destination / "obsolete.tsv").exists()


def test_download_release_installs_verified_cache(tmp_path):
    from core.ecopart_cache_distribution import (
        build_cache_bundle,
        download_github_release_cache,
    )

    source = tmp_path / "source"
    (source / "files").mkdir(parents=True)
    (source / "manifest.sqlite").write_bytes(b"shared-cache")
    (source / "files" / "abc.tsv").write_text("Profile\tDepth [m]\tSampled volume [L]\nRA62\t2.5\t1\n")
    manifest, archive = build_cache_bundle(source, tmp_path / "release")
    assets = {
        "https://github.test/release": json.dumps(
            {
                "assets": [
                    {"name": manifest.name, "url": "https://github.test/manifest"},
                    {"name": archive.name, "url": "https://github.test/archive"},
                ]
            }
        ).encode(),
        "https://github.test/manifest": manifest.read_bytes(),
        "https://github.test/archive": archive.read_bytes(),
    }

    class Response:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def opener(request):
        url = request.full_url
        if url.endswith("/releases/tags/current"):
            return Response(assets["https://github.test/release"])
        return Response(assets[url])

    destination = tmp_path / "clone" / "ecopart_cache"
    download_github_release_cache("owner/repo", "current", "read-token", destination, opener=opener)

    assert (destination / "manifest.sqlite").read_bytes() == b"shared-cache"


def test_consumer_bootstrap_downloads_only_when_local_cache_is_absent(tmp_path, monkeypatch):
    import core.ecopart_cache_distribution as distribution

    destination = tmp_path / "cache"
    monkeypatch.setenv("ECOPART_CACHE_MODE", "consumer")
    monkeypatch.setenv("ECOPART_CACHE_RELEASE_REPOSITORY", "owner/repo")
    monkeypatch.setenv("ECOPART_CACHE_RELEASE_TAG", "current")
    captured = []

    def fake_download(repository, tag, token, target):
        captured.append((repository, tag, token, target))
        target.mkdir(parents=True)
        (target / "manifest.sqlite").write_bytes(b"cache")

    monkeypatch.setattr(distribution, "download_github_release_cache", fake_download)

    assert distribution.bootstrap_consumer_cache(destination) is True
    assert distribution.bootstrap_consumer_cache(destination) is False
    assert captured == [("owner/repo", "current", None, destination)]
