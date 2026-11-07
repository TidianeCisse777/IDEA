"""Scientific and download contracts, independent of the production warehouse."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from populate_ecopart import parse_export, profile_zone, resolve_sample_links, task_link_from_response


def test_bin_edges_normalized_and_leading_zero_profile_preserved():
    data = (Path(__file__).parent / "fixtures/ecopart/bins.tsv").read_bytes()
    rows = parse_export(data)
    assert [r["depth_min"] for r in rows] == [0, 5, 10]
    assert [r["volume"] for r in rows] == [100, 200, 150]
    assert {r["profile"] for r in rows} == {"001_profile"}


@pytest.mark.parametrize(
    "rows",
    [
        "p\t0\t100\np\t2.5\t100\n",
        "p\t0\t-1\n",
        "p\t0\t\n",
        "\t0\t100\n",
        "p\tNaN\t100\n",
    ],
)
def test_invalid_or_conflicting_bins_are_not_silently_dropped(rows):
    with pytest.raises(ValueError):
        parse_export(("Profile\tDepth [m]\tSampled volume [L]\n" + rows).encode())


def test_exact_profile_links_no_suffix_guessing_or_cross_project_link():
    samples = [
        {"id": 1, "sample_orig_id": "p", "profile_id": "hdr1"},
        {"id": 2, "sample_orig_id": "other", "profile_id": "hdr2"},
        {"id": 3, "sample_orig_id": "p_001", "profile_id": None},
    ]
    links, missing = resolve_sample_links(samples, {"p", "hdr2"})
    assert [(x["sample_id"], x["profile"]) for x in links] == [(1, "p"), (2, "hdr2")]
    assert missing == [3]


def test_ambiguous_profile_match_rejected():
    with pytest.raises(ValueError, match="ambig"):
        resolve_sample_links(
            [{"id": 1, "sample_orig_id": "p", "profile_id": "q"}], {"p", "q"}
        )


def test_task_identity_never_selected_from_another_export():
    assert (
        task_link_from_response("https://ecopart.obs-vlfr.fr/Task/Show/123", "")
        == "/Task/Show/123"
    )
    assert (
        task_link_from_response(
            "https://ecopart.obs-vlfr.fr/Task/Create/TaskPartExport",
            '<a href="/Task/Show/123">task</a>',
        )
        == "/Task/Show/123"
    )
    with pytest.raises(ValueError):
        task_link_from_response(
            "https://ecopart.obs-vlfr.fr/Task/Create/TaskPartExport",
            '<a href="/Task/Show/123">a</a><a href="/Task/Show/124">b</a>',
        )


def test_particle_units_and_biovolume_kept_separate():
    from populate_ecopart import particle_values

    values = particle_values(
        {
            "LPM (0.512-1.02 mm) [# l-1]": "2.5",
            "LPM biovolume (0.512-1.02 mm) [mm3 l-1]": "7",
        }
    )
    assert len(values) == 1
    assert values[0][1:3] == (512, 1020)
    assert values[0][-2:] == (2.5, "# l-1")


def test_zip_identical_member_deduplication_but_zoo_not_particle_bins(tmp_path):
    import zipfile

    from populate_ecopart import archive_tables, export_rows

    content = b"Profile\tDepth [m]\tSampled volume [L]\np\t0\t100\n"
    path = tmp_path / "test.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export_PAR_p.tsv", content)
        with pytest.warns(UserWarning):
            archive.writestr("export_PAR_p.tsv", content)
        archive.writestr("export_ZOO_p.tsv", content)
    assert len(export_rows(path)) == 1
    assert archive_tables(path)[1] == ["export_PAR_p.tsv"]


@pytest.fixture
def warehouse_db():
    """Opt-in integration test in a new disposable database, never production."""
    import os
    import uuid

    import psycopg
    from populate_ecopart import ROOT, connection
    from psycopg import sql
    from psycopg.rows import dict_row

    if os.getenv("ECOPART_INTEGRATION_TESTS") != "1":
        pytest.skip("Set ECOPART_INTEGRATION_TESTS=1 for local PostgreSQL fixture")
    admin = connection()
    admin.autocommit = True
    name = "ecopart_test_" + uuid.uuid4().hex[:12]
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    parameters = admin.info.get_parameters()
    parameters["dbname"] = name
    # get_parameters deliberately excludes the password.
    parameters["password"] = os.getenv("WAREHOUSE_POSTGRES_PASSWORD")
    conn = psycopg.connect(**parameters, row_factory=dict_row)
    try:
        conn.execute((ROOT / "docs/warehouse_schema_proposal.sql").read_text())
        conn.execute((ROOT / "docs/warehouse_ecopart_migration.sql").read_text())
        conn.execute("""INSERT INTO warehouse.dataset_version
            (source_instance,dataset_key,version_key,file_manifest_uri,sha256)
            VALUES ('ecotaxa','1','test','fixture','test');
            INSERT INTO warehouse.ecotaxa_sample (dataset_version_id,project_id,sample_id,sample_orig_id)
            VALUES (1,1,'100','001_profile');
            INSERT INTO warehouse.ecotaxa_object (sample_id,object_id,category_name,depth_min_m)
            VALUES (1,'o1','copepod',0),(1,'o2','copepod',4.999),(1,'o3','copepod',5),
                   (1,'o4','copepod',15),(1,'o5',NULL,NULL);""")
        conn.commit()
        yield conn
    finally:
        conn.close()
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        admin.close()


def test_real_sql_join_zeros_boundaries_and_idempotence(warehouse_db):
    from populate_ecopart import load_project

    conn = warehouse_db
    path = Path(__file__).parent / "fixtures/ecopart/bins.tsv"
    proof = {"1": {"evidence": [{"method": "fixture"}]}}
    result = load_project(conn, path, 10, [1], proof)
    assert result["mapped_objects"] == 3
    assert result["unmapped_objects"] == 2
    rows = conn.execute(
        "SELECT n_objects_taxon,abundance_uvp_ind_m3 FROM explore.uvp_taxon_abundance ORDER BY depth_min_m"
    ).fetchall()
    assert [r["n_objects_taxon"] for r in rows] == [2, 1, 0]
    assert [float(r["abundance_uvp_ind_m3"]) for r in rows] == [20, 5, 0]
    assert (
        conn.execute("SELECT count(*) AS n FROM explore.uvp_objects").fetchone()["n"]
        == 5
    )
    conn.commit()
    assert load_project(conn, path, 10, [1], proof) == result
    assert (
        conn.execute("SELECT count(*) AS n FROM warehouse.uvp_bin").fetchone()["n"] == 3
    )
    conn.commit()


def test_real_sql_failure_rolls_back_whole_project(warehouse_db, tmp_path, monkeypatch):
    import populate_ecopart

    conn = warehouse_db
    path = Path(__file__).parent / "fixtures/ecopart/bins.tsv"

    def broken(_):
        raise ValueError("simulated malformed particle class after COPY")

    monkeypatch.setattr(populate_ecopart, "particle_values", broken)
    with pytest.raises(ValueError):
        populate_ecopart.load_project(conn, path, 10, [1], {"1": {"evidence": []}})
    assert (
        conn.execute("SELECT count(*) AS n FROM warehouse.uvp_profile").fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM warehouse.dataset_version WHERE source_instance='ecopart'"
        ).fetchone()["n"]
        == 0
    )
    conn.commit()


def test_task_identity_from_creation_confirmation_without_link():
    # Real EcoPart answer for project 61 (2026-11-02): the task id, no href.
    url = "https://ecopart.obs-vlfr.fr/Task/Create/TaskPartExport"
    html = "<h3>Task 61970 subprocess Created</h3><script>x='/Task/Show/61970'</script>"
    assert task_link_from_response(url, html) == "/Task/Show/61970"
    with pytest.raises(ValueError):
        task_link_from_response(url, "Task 1 subprocess Created Task 2 subprocess Created")
    with pytest.raises(ValueError):
        task_link_from_response(url, "<p>rien</p>")


def test_profile_zone_is_ambiguous_when_its_samples_disagree():
    # GreenEdge 2016 at 70 N: the same profile is Baie de Baffin in project 149 and
    # Detroit de Davis in 20890; it was loaded with an empty zone marked "assigned".
    zone = dict(marine_zone_source="IHO Marine Regions v3", marine_zone_version="registry-v1",
                marine_zone_assignment_status="assigned")
    baffin = dict(zone, marine_zone_key="Baie de Baffin", marine_zone_name="Baie de Baffin")
    davis = dict(zone, marine_zone_key="Détroit de Davis", marine_zone_name="Détroit de Davis")
    assert profile_zone([baffin, davis]) == ("AMBIGUOUS", "AMBIGUOUS", "IHO Marine Regions v3", "registry-v1", "ambiguous")
    assert profile_zone([baffin, dict(baffin)]) == ("Baie de Baffin", "Baie de Baffin", "IHO Marine Regions v3",
                                                    "registry-v1", "assigned")
    assert profile_zone([]) == (None, None, None, None, None)


def test_ecopart_time_is_read_from_the_metadata_summary():
    # Every UVP profile was at midnight: the EcoTaxa samples give only the date.
    from populate_ecopart import ecopart_time
    assert ecopart_time("2015-04-18 18:12:10") == "2015-04-18T18:12:10+00:00"
    assert ecopart_time("2015-04-18 18:12") == "2015-04-18T18:12:00+00:00"
    assert ecopart_time("") is None and ecopart_time(None) is None and ecopart_time("18/04/2015") is None
