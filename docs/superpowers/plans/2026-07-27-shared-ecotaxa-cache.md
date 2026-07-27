# Shared EcoTaxa Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every authorized repository clone the same validated EcoTaxa SQLite cache without giving consumers EcoTaxa credentials.

**Architecture:** Keep `data/ecotaxa_cache.sqlite` and its current schema unchanged. A publisher packages a validated cache as a gzip archive plus JSON manifest in a GitHub release; a consumer MCP process downloads, validates, and atomically installs that exact SQLite file before serving requests. Publisher mode retains the existing EcoTaxa sync and nightly refresh behavior; consumer mode never creates an EcoTaxa client or refreshes from EcoTaxa.

**Tech Stack:** Python standard library (`gzip`, `hashlib`, `json`, `urllib`), SQLite, FastAPI/MCP lifespan, Bash, GitHub CLI for publisher-side release upload, pytest.

## Global Constraints

- The installed cache path remains `data/ecotaxa_cache.sqlite`; no schema, table, LangChain tool, or MCP endpoint changes.
- The distributed data is the exact SQLite bytes after gzip decompression.
- `ECOTAXA_USERNAME` and `ECOTAXA_PASSWORD` are publisher-only secrets; neither may be added to code, tests, docs examples containing a real value, manifests, archives, logs, or releases.
- Consumer installation must reject an invalid hash, invalid size, unavailable archive, missing mandatory manifest field, stale schema, empty cache, or failed sync.
- Consumer installation must use a temporary sibling file and `Path.replace()` only after all validation succeeds.
- The default remains publisher mode to preserve existing deployments; fresh consumer clones explicitly set `ECOTAXA_CACHE_MODE=consumer`.

---

## File Structure

- `core/ecotaxa_browser/cache/distribution.py` — Pure cache validation, gzip package creation, manifest parsing, verified archive installation, and GitHub release asset retrieval.
- `scripts/publish_ecotaxa_cache.py` — Publisher CLI: validates local cache, builds assets, then invokes authenticated `gh release create/upload`.
- `core/mcp/ecotaxa_server.py` — Chooses publisher sync versus consumer artifact bootstrap during the MCP lifespan.
- `start.sh` — Requires EcoTaxa credentials only in publisher mode and preserves the existing health gate in both modes.
- `.env.example`, `docker-compose.yml`, `README.md`, `core/mcp/README.md` — Describe and forward consumer release configuration without secrets.
- `tests/test_ecotaxa_cache_distribution.py` — Real SQLite archive/package/install tests with local fixtures and injected HTTP opener.
- `tests/test_ecotaxa_cache_bootstrap.py`, `tests/test_shareable_setup.py` — Lifespan mode and startup/configuration regression tests.

## Task 1: Package and validate the unchanged SQLite format

**Files:**
- Create: `core/ecotaxa_browser/cache/distribution.py`
- Create: `tests/test_ecotaxa_cache_distribution.py`

**Interfaces:**
- Produces `CacheManifest`, `build_cache_bundle(cache_path, output_dir)`, and `validate_installed_cache(cache_path)`.
- `CacheManifest` serializes `schema_version`, `sha256`, `size_bytes`, `projects_indexed`, `samples_indexed`, and `synced_at`.
- Consumes `SCHEMA_VERSION`, `open_connection`, `cache_counts`, and `latest_sync_status` from the existing cache package.

- [ ] **Step 1: Write the failing package test**

```python
def test_build_cache_bundle_keeps_the_validated_sqlite_bytes(tmp_path):
    cache_path = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite")

    manifest_path, archive_path = build_cache_bundle(cache_path, tmp_path / "release")

    with gzip.open(archive_path, "rb") as stream:
        assert stream.read() == cache_path.read_bytes()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["samples_indexed"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_build_cache_bundle_keeps_the_validated_sqlite_bytes -v`

Expected: FAIL because `core.ecotaxa_browser.cache.distribution` does not exist.

- [ ] **Step 3: Implement the smallest package builder**

```python
def build_cache_bundle(cache_path: Path, output_dir: Path) -> tuple[Path, Path]:
    manifest = validate_installed_cache(cache_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / "ecotaxa_cache.sqlite.gz"
    with cache_path.open("rb") as source, gzip.open(archive_path, "wb") as target:
        shutil.copyfileobj(source, target)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), sort_keys=True) + "\n")
    return manifest_path, archive_path
```

`validate_installed_cache` must read the real SQLite database, require a current schema, positive project/sample counts, and `latest_sync_status(conn)["status"] == "ok"`.

- [ ] **Step 4: Run the package test to verify it passes**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_build_cache_bundle_keeps_the_validated_sqlite_bytes -v`

Expected: PASS.

- [ ] **Step 5: Add the invalid-cache regression test and run it red**

```python
def test_build_cache_bundle_rejects_an_empty_or_unstamped_cache(tmp_path):
    empty_cache = tmp_path / "empty.sqlite"
    conn = open_connection(empty_cache)
    init_schema(conn)
    conn.close()

    with pytest.raises(CacheValidationError, match="empty|sync"):
        build_cache_bundle(empty_cache, tmp_path / "release")
```

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_build_cache_bundle_rejects_an_empty_or_unstamped_cache -v`

Expected: FAIL until cache validation rejects this input.

- [ ] **Step 6: Complete validation and verify Task 1 tests**

Run: `pytest tests/test_ecotaxa_cache_distribution.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add core/ecotaxa_browser/cache/distribution.py tests/test_ecotaxa_cache_distribution.py
git commit -m "feat: package validated EcoTaxa cache"
```

## Task 2: Download, verify, and atomically install a released cache

**Files:**
- Modify: `core/ecotaxa_browser/cache/distribution.py`
- Modify: `tests/test_ecotaxa_cache_distribution.py`

**Interfaces:**
- Produces `install_cache_release(manifest_bytes, archive_stream, destination) -> CacheManifest`.
- Consumes Task 1 `CacheManifest` and `validate_installed_cache`.
- The caller supplies downloaded bytes/stream; the function contains no HTTP policy and is testable with `io.BytesIO`.

- [ ] **Step 1: Write the atomic-install failing test**

```python
def test_install_cache_release_replaces_destination_only_after_verification(tmp_path):
    old_cache = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite", marker="old")
    manifest_path, archive_path = build_cache_bundle(
        seeded_current_cache(tmp_path / "new.sqlite", marker="new"), tmp_path / "release"
    )

    install_cache_release(manifest_path.read_bytes(), io.BytesIO(archive_path.read_bytes()), old_cache)

    assert cache_marker(old_cache) == "new"
    assert not list(tmp_path.glob(".ecotaxa_cache.sqlite.*.tmp"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_install_cache_release_replaces_destination_only_after_verification -v`

Expected: FAIL because `install_cache_release` is not defined.

- [ ] **Step 3: Implement verified staging and replacement**

```python
def install_cache_release(manifest_bytes: bytes, archive_stream: BinaryIO, destination: Path) -> CacheManifest:
    manifest = CacheManifest.from_json(manifest_bytes)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with gzip.GzipFile(fileobj=archive_stream) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
        if temporary.stat().st_size != manifest.size_bytes or sha256_file(temporary) != manifest.sha256:
            raise CacheValidationError("archive integrity check failed")
        installed = validate_installed_cache(temporary)
        if installed.schema_version != manifest.schema_version:
            raise CacheValidationError("schema version mismatch")
        temporary.replace(destination)
        return installed
    finally:
        temporary.unlink(missing_ok=True)
```

- [ ] **Step 4: Run the install test to verify it passes**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_install_cache_release_replaces_destination_only_after_verification -v`

Expected: PASS.

- [ ] **Step 5: Write and run tamper-preservation test**

```python
def test_install_cache_release_preserves_existing_cache_when_hash_is_wrong(tmp_path):
    destination = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite", marker="keep")
    manifest_path, archive_path = build_cache_bundle(
        seeded_current_cache(tmp_path / "new.sqlite", marker="discard"), tmp_path / "release"
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"] = "0" * 64

    with pytest.raises(CacheValidationError, match="integrity"):
        install_cache_release(json.dumps(manifest).encode(), io.BytesIO(archive_path.read_bytes()), destination)
    assert cache_marker(destination) == "keep"
```

Run: `pytest tests/test_ecotaxa_cache_distribution.py -v`

Expected: PASS after the implementation rejects tampering and preserves the old file.

- [ ] **Step 6: Commit Task 2**

```bash
git add core/ecotaxa_browser/cache/distribution.py tests/test_ecotaxa_cache_distribution.py
git commit -m "feat: install shared EcoTaxa cache atomically"
```

## Task 3: Retrieve a GitHub release without EcoTaxa credentials

**Files:**
- Modify: `core/ecotaxa_browser/cache/distribution.py`
- Modify: `tests/test_ecotaxa_cache_distribution.py`
- Create: `scripts/publish_ecotaxa_cache.py`

**Interfaces:**
- Produces `download_github_release_cache(repository, tag, token, destination, opener=urlopen)`.
- Consumes `GITHUB_TOKEN` only to read a private GitHub release; it never reads `ECOTAXA_USERNAME` or `ECOTAXA_PASSWORD`.
- Publisher CLI accepts `--repository`, `--tag`, and `--cache-path`; uses `gh release create` then `gh release upload --clobber`.

- [ ] **Step 1: Write the release-download failing test**

```python
def test_download_github_release_cache_uses_manifest_and_archive_assets(tmp_path):
    release = fake_release_with_assets(tmp_path)
    destination = tmp_path / "data" / "ecotaxa_cache.sqlite"

    download_github_release_cache("owner/repo", "ecotaxa-cache-current", None, destination, opener=release.urlopen)

    assert validate_installed_cache(destination).samples_indexed == 1
    assert release.requested_paths == ["/release", "/manifest", "/archive"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_download_github_release_cache_uses_manifest_and_archive_assets -v`

Expected: FAIL because the download function is absent.

- [ ] **Step 3: Implement the GitHub API boundary and publisher CLI**

```python
def download_github_release_cache(repository, tag, token, destination, *, opener=urlopen):
    release = request_json(f"https://api.github.com/repos/{repository}/releases/tags/{tag}", token, opener)
    assets = {asset["name"]: asset for asset in release["assets"]}
    manifest = request_bytes(assets["manifest.json"]["url"], token, opener, accept="application/octet-stream")
    archive = request_stream(assets["ecotaxa_cache.sqlite.gz"]["url"], token, opener, accept="application/octet-stream")
    return install_cache_release(manifest, archive, destination)
```

The CLI must fail with a clear message when `gh` is unavailable or returns non-zero, and must write its temporary assets outside `data/`.

- [ ] **Step 4: Run the download test and publisher help**

Run: `pytest tests/test_ecotaxa_cache_distribution.py::test_download_github_release_cache_uses_manifest_and_archive_assets -v && python scripts/publish_ecotaxa_cache.py --help`

Expected: test PASS and CLI usage output without requiring a secret.

- [ ] **Step 5: Commit Task 3**

```bash
git add core/ecotaxa_browser/cache/distribution.py scripts/publish_ecotaxa_cache.py tests/test_ecotaxa_cache_distribution.py
git commit -m "feat: distribute EcoTaxa cache through releases"
```

## Task 4: Enforce consumer and publisher behavior in the MCP lifecycle

**Files:**
- Modify: `core/mcp/ecotaxa_server.py`
- Modify: `tests/test_ecotaxa_cache_bootstrap.py`
- Modify: `tests/test_mcp_cache_admin.py`

**Interfaces:**
- `ECOTAXA_CACHE_MODE` accepts only `publisher` or `consumer`, defaults to `publisher`.
- Consumer calls `download_github_release_cache` before yielding the FastAPI lifespan.
- Publisher preserves `_cache_requires_bootstrap`, `_run_full_sync_with_real_client`, and the nightly scheduler.

- [ ] **Step 1: Write consumer lifecycle failing tests**

```python
def test_consumer_lifespan_installs_release_without_constructing_ecotaxa_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOTAXA_CACHE_MODE", "consumer")
    monkeypatch.setenv("ECOTAXA_CACHE_RELEASE_REPOSITORY", "owner/repo")
    monkeypatch.setenv("ECOTAXA_CACHE_RELEASE_TAG", "ecotaxa-cache-current")
    monkeypatch.setattr(server, "download_github_release_cache", install_fixture_release)
    monkeypatch.setattr(server, "EcotaxaClient", pytest.fail)

    with TestClient(server.create_app()):
        assert cache_counts(open_connection(tmp_path / "ecotaxa_cache.sqlite"))["samples_indexed"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ecotaxa_cache_bootstrap.py::test_consumer_lifespan_installs_release_without_constructing_ecotaxa_client -v`

Expected: FAIL because the lifecycle always uses the current sync bootstrap.

- [ ] **Step 3: Implement explicit mode selection**

```python
def _cache_mode() -> Literal["publisher", "consumer"]:
    mode = os.getenv("ECOTAXA_CACHE_MODE", "publisher").lower()
    if mode not in {"publisher", "consumer"}:
        raise RuntimeError("ECOTAXA_CACHE_MODE must be publisher or consumer")
    return cast(Literal["publisher", "consumer"], mode)
```

In consumer mode, require repository and tag variables, call the download function before starting the app, and do not create the scheduler or submit a live sync. In publisher mode, retain the existing code path.

- [ ] **Step 4: Run lifecycle and admin regressions**

Run: `pytest tests/test_ecotaxa_cache_bootstrap.py tests/test_mcp_cache_admin.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add core/mcp/ecotaxa_server.py tests/test_ecotaxa_cache_bootstrap.py tests/test_mcp_cache_admin.py
git commit -m "feat: add EcoTaxa cache consumer mode"
```

## Task 5: Configure consumer startup and operational documentation

**Files:**
- Modify: `start.sh`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `core/mcp/README.md`
- Modify: `tests/test_shareable_setup.py`
- Modify: `tests/test_mcp_compose.py`

**Interfaces:**
- Consumer configuration: `ECOTAXA_CACHE_MODE=consumer`, `ECOTAXA_CACHE_RELEASE_REPOSITORY`, `ECOTAXA_CACHE_RELEASE_TAG`, and optional `GITHUB_TOKEN`.
- Publisher configuration: `ECOTAXA_CACHE_MODE=publisher` plus current EcoTaxa credentials.
- `docker-compose.yml` forwards all cache distribution variables only to `mcp-ecotaxa`.

- [ ] **Step 1: Write failing startup/configuration tests**

```python
def test_consumer_setup_does_not_require_ecotaxa_credentials():
    script = Path("start.sh").read_text(encoding="utf-8")

    result = subprocess.run(
        ["bash", "start.sh", "--help"], text=True, capture_output=True, check=True
    )

    assert "consumer" in script
    assert "publisher" in script
    assert result.returncode == 0
```

Add a compose test that parses the service environment and asserts the four cache distribution variables are passed to `mcp-ecotaxa`, while no consumer documentation asks for EcoTaxa credentials.

- [ ] **Step 2: Run them to verify failure**

Run: `pytest tests/test_shareable_setup.py tests/test_mcp_compose.py -v`

Expected: FAIL because consumer mode is not documented or forwarded.

- [ ] **Step 3: Implement startup selection and docs**

In `start.sh`, build `REQUIRED_ENV_VARS` conditionally: publisher requires the current two EcoTaxa variables; consumer requires repository and tag but not a GitHub token when the release is public. Preserve the existing cache-health gate. Document the maintainer command sequence: rotate exposed password, sync in publisher mode, run publish CLI, then switch collaborators to consumer mode.

- [ ] **Step 4: Run startup/configuration tests and shell syntax check**

Run: `pytest tests/test_shareable_setup.py tests/test_mcp_compose.py -v && bash -n start.sh`

Expected: PASS.

- [ ] **Step 5: Run focused end-to-end verification**

Run: `pytest tests/test_ecotaxa_cache_distribution.py tests/test_ecotaxa_cache_bootstrap.py tests/test_mcp_cache_admin.py tests/test_shareable_setup.py tests/test_mcp_compose.py -v`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add start.sh docker-compose.yml .env.example README.md core/mcp/README.md tests/test_shareable_setup.py tests/test_mcp_compose.py
git commit -m "docs: configure shared EcoTaxa cache consumers"
```
