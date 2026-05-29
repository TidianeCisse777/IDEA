from core.tool_registry.registry import Tool, registry

_code = '''
def inspect_file(file_path, sample_rows=500):
    """Read a user file and return a structured technical report without modifying it.

    The LLM is free to explore the file with pandas or any other library before
    or after calling this function. Use this when you want a consistent, documented
    snapshot of what a file contains — especially before entering Mode Plan.

    Args:
        file_path (str): Path to the file to inspect.
        sample_rows (int): Number of rows to sample for large files.

    Returns:
        dict: Structured report with format, columns, metadata, source_type_guess.
              raw_file_modified is always False.
    """
    import pathlib
    import json

    path = pathlib.Path(file_path)
    warnings = []
    result = {
        "file_path": str(file_path),
        "format": "unknown",
        "n_rows": "unknown",
        "n_columns": "unknown",
        "columns": [],
        "metadata": {
            "encoding": None,
            "delimiter": None,
            "sheet_names": [],
            "netcdf_dimensions": {},
            "netcdf_variables": [],
            "source_metadata": {}
        },
        "source_type_guess": {
            "value": "unknown",
            "confidence": "low",
            "evidence": []
        },
        "warnings": warnings,
        "raw_file_modified": False
    }

    if not path.exists():
        warnings.append(f"File not found: {file_path}")
        return result

    suffix = path.suffix.lower()

    # ── CSV / TSV ──────────────────────────────────────────────────────────────
    if suffix in (".csv", ".tsv", ".txt"):
        import csv as _csv
        import pandas as pd
        import chardet

        with open(path, "rb") as f:
            raw = f.read(min(100_000, path.stat().st_size))
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        result["metadata"]["encoding"] = encoding

        # Detect delimiter: trust extension for .tsv, sniff for .csv/.txt.
        if suffix == ".tsv":
            delimiter = "\t"
        else:
            try:
                sample_text = raw.decode(encoding, errors="replace")
                sniffed = _csv.Sniffer().sniff(sample_text[:4096], delimiters=",;\t|")
                delimiter = sniffed.delimiter
            except _csv.Error:
                delimiter = ","
        result["metadata"]["delimiter"] = delimiter

        try:
            df_sample = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                    nrows=sample_rows, on_bad_lines="skip",
                                    engine="python")

            # Detect EcoTaxa 2-row header: second line contains [t], [f], [n] type codes.
            skip_rows = []
            if _is_ecotaxa_type_row(df_sample):
                skip_rows = [1]
                result["metadata"]["ecotaxa_type_row_skipped"] = True
                warnings.append("EcoTaxa type row ([t]/[f]/[n]) detected and skipped.")
                df_sample = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                        nrows=sample_rows, skiprows=skip_rows,
                                        on_bad_lines="skip", engine="python")

            result["format"] = "tsv" if suffix == ".tsv" else "csv"

            try:
                df_full = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                      skiprows=skip_rows, on_bad_lines="skip",
                                      engine="python", usecols=lambda c: True)
                result["n_rows"] = len(df_full)
            except Exception:
                result["n_rows"] = f">{sample_rows} (sample only)"

            result["n_columns"] = len(df_sample.columns)
            result["columns"] = _describe_columns(df_sample)
            result["source_type_guess"] = _guess_source_type(df_sample.columns.tolist(), {"filename": path.stem})

        except Exception as e:
            warnings.append(f"Could not parse as tabular: {e}")

    # ── Excel ──────────────────────────────────────────────────────────────────
    elif suffix in (".xlsx", ".xls"):
        import pandas as pd

        try:
            xl = pd.ExcelFile(path)
            sheet_names = xl.sheet_names
            result["metadata"]["sheet_names"] = sheet_names
            result["format"] = "xlsx"

            df_sample = xl.parse(sheet_names[0], nrows=sample_rows)
            result["n_columns"] = len(df_sample.columns)
            result["columns"] = _describe_columns(df_sample)

            try:
                df_full = xl.parse(sheet_names[0])
                result["n_rows"] = len(df_full)
            except Exception:
                result["n_rows"] = f">{sample_rows} (sample only)"

            result["source_type_guess"] = _guess_source_type(df_sample.columns.tolist(), {})

        except Exception as e:
            warnings.append(f"Could not parse Excel file: {e}")

    # ── NetCDF ─────────────────────────────────────────────────────────────────
    elif suffix in (".nc", ".nc4", ".netcdf"):
        try:
            import xarray as xr
            ds = xr.open_dataset(path)
            result["format"] = "netcdf"
            result["metadata"]["netcdf_dimensions"] = {k: v for k, v in ds.dims.items()}
            result["metadata"]["netcdf_variables"] = list(ds.data_vars.keys())
            result["metadata"]["source_metadata"] = {k: str(v) for k, v in ds.attrs.items()}
            result["n_columns"] = len(ds.data_vars)
            result["n_rows"] = "n/a (gridded)"
            result["source_type_guess"] = {
                "value": "likely_amundsen_ctd",
                "confidence": "low",
                "evidence": ["NetCDF format — consistent with oceanographic data"]
            }
            ds.close()
        except Exception as e:
            warnings.append(f"Could not parse NetCDF: {e}")

    # ── JSON ───────────────────────────────────────────────────────────────────
    elif suffix == ".json":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            result["format"] = "json"
            if isinstance(data, list) and data:
                result["n_rows"] = len(data)
                result["n_columns"] = len(data[0]) if isinstance(data[0], dict) else "unknown"
            elif isinstance(data, dict):
                result["n_rows"] = 1
                result["n_columns"] = len(data)
        except Exception as e:
            warnings.append(f"Could not parse JSON: {e}")

    else:
        warnings.append(f"Unsupported format: {suffix}. Supported: csv, tsv, xlsx, xls, nc, json.")

    return result


def _is_ecotaxa_type_row(df):
    """Return True if the first data row looks like an EcoTaxa type-annotation row.

    EcoTaxa bulk TSV exports insert a second header line where every cell is
    one of [t] (text), [f] (float), or [n] (numeric). Detecting this prevents
    the type row from corrupting dtype inference and row counts.
    """
    import re as _re
    if len(df) == 0:
        return False
    _TYPE_RE = _re.compile(r"^\\[([tfnTs])\\]$")
    first_row = df.iloc[0].astype(str).str.strip()
    non_empty = [v for v in first_row if v not in ("nan", "", "NaN")]
    return len(non_empty) > 0 and all(_TYPE_RE.match(v) for v in non_empty)


def _describe_columns(df):
    """Build per-column descriptor from a pandas DataFrame sample."""
    import pandas as pd
    cols = []
    for col in df.columns:
        series = df[col]
        missing_count = int(series.isna().sum())
        n = len(series)
        missing_rate = round(missing_count / n, 3) if n > 0 else 0.0
        sample_vals = [v for v in series.dropna().head(5).tolist()]

        guess, unit, confidence = _semantic_guess(col, series)

        cols.append({
            "name": col,
            "dtype": str(series.dtype),
            "missing_count": missing_count,
            "missing_rate": missing_rate,
            "sample_values": sample_vals,
            "semantic_guess": guess,
            "unit_guess": unit,
            "confidence": confidence
        })
    return cols


def _semantic_guess(col_name, series):
    """Heuristic semantic guess from column name only. Low confidence by design."""
    name = col_name.lower()

    rules = [
        (["depth", "profondeur", "depth_min", "depth_max"], "depth", "m", "medium"),
        (["lat", "latitude"],                                "latitude", "degrees", "high"),
        (["lon", "longitude"],                               "longitude", "degrees", "high"),
        (["time", "date", "datetime", "timestamp"],          "time", None, "medium"),
        (["classif", "taxon", "taxonom", "species"],         "taxon", None, "medium"),
        (["classif_qual", "valid"],                          "taxonomic_validation_status", None, "medium"),
        (["vol", "volume"],                                  "sample_volume", "L or m3", "low"),
        (["img", "image", "object_id", "obj_id"],            "image_id", None, "low"),
        (["station", "sta_"],                                "station", None, "medium"),
        (["profile", "profile_id"],                          "profile_id", None, "medium"),
        (["pixel", "area", "esd", "major", "minor"],         "size_or_morphometry", "pixels or mm", "low"),
    ]

    for keywords, role, unit, conf in rules:
        if any(k in name for k in keywords):
            return role, unit, conf

    return None, None, "low"


def _guess_source_type(column_names, metadata):
    """Guess source type from column name patterns. Never certain."""
    filename = (metadata or {}).get("filename", "").lower()
    if "bio_oracle" in filename or "bio-oracle" in filename:
        return {"value": "likely_environmental_model", "confidence": "high",
                "evidence": [f"filename contains 'bio_oracle': {filename}"]}

    names_lower = [c.lower() for c in column_names]
    evidence = []
    scores = {"likely_ecotaxa": 0, "likely_ecopart": 0,
              "likely_amundsen_ctd": 0, "likely_lab_data": 0,
              "likely_neolabs_taxon": 0}

    ecotaxa_signals = ["classif_id", "classif_qual", "object_id", "obj_depth",
                       "acq_", "process_", "img_file", "object_lat", "object_lon"]
    ecopart_signals = ["profile_id", "nb_part", "volume_analyzed",
                       "depth_min", "depth_max", "biovolume"]
    ctd_signals = ["te90", "psal", "oxym", "fluo", "tur9", "sigt",
                   "latitude", "longitude", "station"]
    lab_signals = ["lipid", "carbon", "biomass", "drymass", "wax_ester",
                   "fatty_acid", "tl_", "dw_"]
    neolabs_taxon_signals = [
        "sample_id", "analysis_id", "analysis_contract", "zooplankton_category",
        "taxon_life_development_stage", "taxon_size_category",
        "depth_calc_net_filtered_vol", "depth_calc_vol", "flowmeter_calc_vol",
        "c1_abund", "c2_abund", "c3_abund", "c4_abund", "c5_abund",
        "m_abund", "f_abund", "cop_ns_abund", "copepodid_abund",
        "n1_abund", "n2_abund", "large fract", "small fract", "total abundance",
        "c1_biomass", "c2_biomass", "c3_biomass", "c4_biomass", "c5_biomass",
        "m_biomass", "f_biomass", "cop_ns_biomass", "copepodid_biomass",
        "n1_biomass", "n2_biomass",
    ]

    for sig in ecotaxa_signals:
        if any(sig in n for n in names_lower):
            scores["likely_ecotaxa"] += 1
            evidence.append(f"column matching EcoTaxa pattern: {sig}")

    for sig in ecopart_signals:
        if any(sig in n for n in names_lower):
            scores["likely_ecopart"] += 1
            evidence.append(f"column matching EcoPart pattern: {sig}")

    for sig in ctd_signals:
        if any(sig in n for n in names_lower):
            scores["likely_amundsen_ctd"] += 1
            evidence.append(f"column matching CTD pattern: {sig}")

    for sig in lab_signals:
        if any(sig in n for n in names_lower):
            scores["likely_lab_data"] += 1
            evidence.append(f"column matching lab data pattern: {sig}")

    for sig in neolabs_taxon_signals:
        if any(sig in n for n in names_lower):
            scores["likely_neolabs_taxon"] += 1
            evidence.append(f"column matching NeoLabs taxonomy pattern: {sig}")

    best = max(scores, key=scores.get)
    top_score = scores[best]

    if top_score == 0:
        return {"value": "unknown", "confidence": "low", "evidence": []}

    confidence = "high" if top_score >= 3 else ("medium" if top_score >= 2 else "low")
    return {"value": best, "confidence": confidence, "evidence": evidence[:5]}


def infer_column_roles(columns, metadata=None):
    """Propose semantic role candidates for a list of column descriptors.

    This is a structured helper — call it after inspect_file and optionally
    after querying the knowledge base for unclear columns. It does pattern
    matching only; it does not rename columns or impose a schema.

    Args:
        columns (list): List of column dicts from inspect_file output.
        metadata (dict, optional): File metadata from inspect_file output.

    Returns:
        dict: Roles with confidence and evidence, plus unmatched columns.
    """
    roles = []
    matched = set()
    columns_are_dicts = bool(columns) and isinstance(columns[0], dict)
    col_names = [c["name"] for c in columns] if columns_are_dicts else [str(c) for c in columns]
    source_type = (metadata or {}).get("source_type_guess", {}).get("value")
    if not source_type or source_type == "unknown":
        source_type = _guess_source_type(col_names, metadata or {}).get("value", "unknown")

    common_patterns = {
        "sample_metadata":          ["sample_id", "analysis_id", "analysis_contract", "sampling_net_id"],
        "campaign_context":         ["project", "cruise", "deployment", "gear", "tow_type", "mesh_size", "cast_number"],
        "file_name":                ["filename", "rawfilename", "file_name"],
        "platform":                 ["platform_name", "platform_id"],
        "station":                  ["station", "sta_"],
        "profile_id":               ["profile_id", "profileid", "profile"],
        "depth":                    ["depth", "profondeur"],
        "sample_depth":             ["sample_depth", "depth_min", "depth_max", "min_sample_depth", "max_sample_depth"],
        "latitude":                 ["lat", "latitude"],
        "longitude":                ["lon", "longitude"],
        "time":                     ["time", "date", "datetime", "timestamp", "yyyy-mm-dd", "hh:mm", "utc"],
        "cast_number":              ["cast_number", "cast"],
        "taxon":                    ["classif_id", "classif_auto_id", "taxon", "taxonom", "species"],
        "taxonomic_validation_status": ["classif_qual", "valid"],
        "taxonomic_rank":           ["kingdom", "phylum", "class", "order", "family"],
        "taxon_life_stage":         ["life_development_stage", "development_stage", "life_stage"],
        "taxon_size_category":      ["size_category"],
        "abundance_measurement":    ["abund", "abundance", "nbr of ind", "ind./m3", "ind./l", "total abundance"],
        "biomass_measurement":      ["biomass", "µg c", "ug c", "mg c"],
        "sample_volume":            ["sampled volume", "volume_analyzed", "volume analyzed", "depth_calc_net_filtered_vol", "depth_calc_vol", "flowmeter_calc_vol", "volume"],
        "image_id":                 ["object_id", "obj_id", "objid", "img_file", "image"],
        "pixel_calibration":        ["acq_pixel", "process_pixel"],
        "size_or_morphometry":      ["area", "esd", "major", "minor", "perimeter", "feret", "width", "height"],
        "environmental_variable":   ["te90", "psal", "oxym", "flor", "fluo", "temp", "sal", "oxygen", "cpar", "fcdom", "density anomaly", "potential temperature", "practical salinity", "conductivity", "par", "spar", "nitrate"],
        "pressure":                 ["pres", "pressure"],
        "fluorescence":             ["flor", "fluorescence"],
        "nitrate":                  ["ntra", "nitrate"],
        "conductivity":             ["conductivity"],
        "par":                      ["par"],
        "quality_flag":             ["qc flag", "quality_flag", "flag"],
        "auxiliary_field":          ["extrames", "aux"],
        "size_fraction_concentration": ["lpm", "# l-1"],
        "size_fraction_biovolume":  ["biovolume", "mm3 l-1"],
    }

    ecotaxa_patterns = {
        "taxon":                    ["object_class"],
        "profile_id":               ["profile_id", "profile"],
        "pixel_calibration":        ["acq_pixel", "process_pixel"],
        "annotation_metadata":      [
            "object_annotation", "annotation_person", "annotation_email",
            "annotation_date", "annotation_time", "annotation_status",
            "annotation_category", "annotation_hierarchy", "complement_info",
            "object_link",
        ],
        "sample_metadata":          ["sample_"],
        "acquisition_metadata":     ["acq_"],
        "processing_metadata":      ["process_", "processid"],
        "technical_metadata":       ["object_random_value", "object_sunpos"],
        "image_geometry":           [
            "object_bx", "object_by", "object_angle", "object_tag",
            "object_range", "object_centroids", "object_cv", "object_sr",
            "object_cdexc",
        ],
        "image_morphometry":        [
            "object_mean", "object_stddev", "object_mode", "object_min", "object_max",
            "object_x", "object_y", "object_xm", "object_ym", "object_perim",
            "object_circ", "object_intden", "object_median", "object_skew",
            "object_kurt", "object_xstart", "object_ystart", "object_fractal",
            "object_slope", "object_histcum", "object_xmg", "object_ymg",
            "object_nb", "object_comp", "object_symetrie", "object_convperim",
            "object_fcons", "object_thickr",
        ],
    }

    ecopart_patterns = {
        "sample_volume":            ["sampled volume", "volume_analyzed", "volume", "vol", "sampled volume [l]"],
        "depth":                    ["depth_min", "depth_max", "depth", "depth [m]"],
        "taxon":                    ["taxon", "species", "classif"],
        "profile_id":               ["profile_id", "profile"],
        "station":                  ["station"],
        "lab_measurement":          ["biovolume", "biomass"],
        "campaign_context":         ["project", "rawfilename"],
        "quality_flag":             ["qc flag"],
        "auxiliary_field":          ["extrames"],
        "environmental_variable":   ["chloro fluo", "conductivity", "cpar", "fcdom", "in situ density anomaly", "nitrate", "oxygen", "par", "potential density anomaly", "potential temperature", "practical salinity", "temperature"],
    }

    ctd_patterns = {
        "campaign_context":         ["filename", "cruise_name", "cruise_number", "cast_number", "platform_name", "platform_id"],
        "station":                  ["station"],
        "latitude":                 ["latitude", "lat"],
        "longitude":                ["longitude", "lon"],
        "time":                     ["time", "date", "datetime", "timestamp"],
        "environmental_variable":   ["te90", "psal", "oxym", "flor", "fluo", "temp", "sal", "oxygen", "sigt", "tur9", "ntra", "par"],
        "pressure":                 ["pres"],
    }

    neolabs_taxon_patterns = {
        "time":                     ["deployment_date_start", "deployment_time_start", "sample_time", "sampling_date", "date", "time"],
        "sample_volume":            ["depth_calc_net_filtered_vol", "depth_calc_vol", "flowmeter_calc_vol"],
        "sample_depth":             ["min_sample_depth", "max_sample_depth", "depth [m]", "sample_depth"],
        "sample_metadata":          ["sample_id", "analysis_id", "analysis_contract", "sampling_net_id"],
        "campaign_context":         ["station_name", "cast_number", "gear", "tow_type", "net_mesh_size"],
        "taxon":                    ["taxon_id", "zooplankton_category"],
        "taxonomic_rank":           ["kingdom", "phylum", "class", "order", "family"],
        "taxon_life_stage":         ["taxon_life_development_stage"],
        "taxon_size_category":      ["taxon_size_category"],
        "abundance_measurement":    ["sample_abund", "abund (ind./m3", "abundance", "large fract", "small fract", "total abundance"],
        "biomass_measurement":      ["biomass"],
    }

    lab_patterns = {
        "lab_measurement":          ["lipid", "carbon", "biomass", "drymass", "wax_ester", "fatty_acid", "tl_", "dw_"],
        "sample_volume":            ["volume", "vol"],
        "taxon":                    ["taxon", "species", "classif"],
        "taxonomic_rank":           ["kingdom", "phylum", "class", "order", "family"],
        "time":                     ["time", "date", "datetime", "timestamp"],
        "campaign_context":         ["project", "gear", "tow_type"],
    }

    source_specific_patterns = {
        "likely_ecotaxa": ecotaxa_patterns,
        "likely_ecopart": ecopart_patterns,
        "likely_amundsen_ctd": ctd_patterns,
        "likely_neolabs_taxon": neolabs_taxon_patterns,
        "likely_lab_data": lab_patterns,
    }

    role_patterns = {}
    for role, keywords in source_specific_patterns.get(source_type, {}).items():
        role_patterns.setdefault(role, [])
        role_patterns[role].extend(keywords)
    for role, keywords in common_patterns.items():
        role_patterns.setdefault(role, [])
        role_patterns[role].extend(keywords)

    for col in col_names:
        col_lower = col.lower()
        found = False
        for role, keywords in role_patterns.items():
            if any(k in col_lower for k in keywords):
                confidence = "high" if col_lower in keywords else "medium"
                roles.append({
                    "role": role,
                    "column": col,
                    "confidence": confidence,
                    "evidence": [f"column name contains pattern for {role}"]
                })
                matched.add(col)
                found = True
                break
        if not found and columns_are_dicts:
            col_dict = next((c for c in columns if c["name"] == col), {})
            if col_dict.get("semantic_guess"):
                roles.append({
                    "role": col_dict["semantic_guess"],
                    "column": col,
                    "confidence": col_dict.get("confidence", "low"),
                    "evidence": ["semantic_guess from inspect_file"]
                })
                matched.add(col)

    unmatched = [c for c in col_names if c not in matched]
    warnings = []
    if unmatched:
        warnings.append(
            f"{len(unmatched)} columns not matched to a role — "
            "consider querying the knowledge base for their definitions."
        )

    return {
        "roles": roles,
        "unmatched_columns": unmatched,
        "warnings": warnings
    }


def collect_column_definitions(file_report, session_id=None):
    """Batch-query the copepod RAG corpus for every column in a file_report.

    Calls ``describe_column`` per column, filters out unknown columns
    (RAG returned confidence="unknown"), and returns the list of
    definition dicts ready to pass to ``format_inspect_report``.

    Resilient: a failing RAG call on one column does not stop the batch.

    Args:
        file_report (dict): Output of ``inspect_file``.
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        list[dict]: List of describe_column results for columns the RAG knows.
    """
    src = (file_report.get("source_type_guess") or {}).get("value")
    if isinstance(src, str) and src.startswith("likely_"):
        src = src[len("likely_"):]

    defs = []
    for col in file_report.get("columns") or []:
        name = col.get("name")
        if not name:
            continue
        try:
            d = describe_column(name, source_hint=src, session_id=session_id)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("confidence") == "unknown":
            continue
        defs.append(d)
    return defs


def format_inspect_report(file_report, column_definitions=None):
    """Render an inspect_file result as a Markdown report.

    Use this instead of ``print(file_report)`` (Python's default dict repr is
    unreadable for wide files). Output is markdown-formatted so it renders
    nicely when included in an assistant text reply: H1 title, header lines
    with bold keys, a full columns table, warnings and source evidence as
    bullet lists. Every column appears — no truncation, no ellipsis.

    When ``column_definitions`` is provided (list of describe_column results,
    e.g. from ``collect_column_definitions``), the matching RAG definition,
    unit and critical notes are rendered in the row's last column.

    Args:
        file_report (dict): The dict returned by ``inspect_file``.
        column_definitions (list[dict], optional): RAG definitions per column.

    Returns:
        str: Markdown text rendering of the full report.
    """
    defs_by_col = {}
    if column_definitions:
        for d in column_definitions:
            if isinstance(d, dict) and d.get("column"):
                defs_by_col[d["column"]] = d
    fr = file_report or {}

    def _md_escape_cell(value):
        s = str(value) if value is not None else ""
        # Pipes inside cells break markdown tables; HTML entity renders as `|`
        # in every renderer and avoids backslash-escape parsing edge cases.
        return s.replace("|", "&#124;").replace(chr(10), " ").replace(chr(13), " ")

    _SOURCE_LABELS = {
        "likely_ecotaxa": "export EcoTaxa",
        "likely_ecopart": "export EcoPart",
        "likely_neolabs_taxon": "données NeoLab",
        "likely_amundsen_ctd": "CTD Amundsen",
        "likely_environmental_model": "modèle environnemental",
        "likely_lab_data": "données labo",
    }
    raw_path = fr.get("file_path", "unknown")
    _fname = raw_path.rsplit("/", 1)[-1] if isinstance(raw_path, str) and "/" in raw_path else str(raw_path)
    _stem = _fname.rsplit(".", 1)[0] if "." in _fname else _fname
    _stem_display = _stem.replace("_", " ")
    _n_rows = fr.get("n_rows", "?")
    _n_cols = fr.get("n_columns", "?")
    _src_label = _SOURCE_LABELS.get((fr.get("source_type_guess") or {}).get("value", ""), "inconnu")
    _title = f"📄 {_src_label} — {_stem_display} ({_n_rows} × {_n_cols})"

    lines = []
    lines.append("# RAPPORT D'INSPECTION")
    lines.append(f"<!-- report-title: {_title} -->")
    lines.append("")
    lines.append(f"- **file_path** : `{fr.get('file_path', 'unknown')}`")
    lines.append(
        f"- **format** : `{fr.get('format', 'unknown')}`"
        f"  •  **n_rows** : `{fr.get('n_rows', 'unknown')}`"
        f"  •  **n_columns** : `{fr.get('n_columns', 'unknown')}`"
    )

    src = fr.get("source_type_guess") or {}
    src_value = src.get("value", "unknown")
    src_conf = src.get("confidence", "low")
    lines.append(f"- **source_type_guess** : `{src_value}` (confidence: `{src_conf}`)")

    meta = fr.get("metadata") or {}
    enc = meta.get("encoding")
    delim = meta.get("delimiter")
    sheet_names = meta.get("sheet_names") or []
    if enc or delim:
        lines.append(
            f"- **encoding** : `{enc or 'n/a'}`  •  **delimiter** : `{delim or 'n/a'}`"
        )
    if sheet_names:
        lines.append(f"- **sheet_names** : `{sheet_names}`")

    cols = fr.get("columns") or []
    lines.append("")
    lines.append(f"## Columns ({len(cols)})")
    lines.append("")
    if not cols:
        lines.append("_(no columns parsed)_")
    else:
        lines.append("| # | Column | Dtype | Missing | Samples | Semantic | RAG definition |")
        lines.append("|---|--------|-------|---------|---------|----------|-----------------|")
        for idx, c in enumerate(cols, start=1):
            name = str(c.get("name", ""))
            dtype = str(c.get("dtype", ""))
            mc = c.get("missing_count", 0)
            mr = c.get("missing_rate", 0.0)
            try:
                mr_pct = f"{float(mr) * 100:.1f}%"
            except (TypeError, ValueError):
                mr_pct = str(mr)
            samples = c.get("sample_values") or []
            samples_short = samples[:3]
            sem = c.get("semantic_guess")
            unit = c.get("unit_guess")
            conf = c.get("confidence", "low")
            sem_cell = f"`{sem}` ({conf})" if sem else "—"
            if unit:
                sem_cell = f"{sem_cell} unit=`{unit}`"

            rag = defs_by_col.get(name)
            if rag:
                rag_conf = rag.get("confidence", "unknown")
                doc = rag.get("rag_doc_ref") or rag.get("source_file") or "RAG"
                unit_r = rag.get("unit")
                unit_part = f" [unit `{unit_r}`]" if unit_r else ""
                defi = (rag.get("definition") or "").strip()
                rag_cell = f"{defi}{unit_part} _(conf: {rag_conf}, src: `{doc}`)_"
                notes = rag.get("critical_notes") or []
                if notes:
                    note_text = " ".join(f"[!] {n}" for n in notes[:2])
                    rag_cell = f"{rag_cell} {note_text}"
            else:
                rag_cell = "—"

            row = (
                f"| {idx} | `{_md_escape_cell(name)}` | `{_md_escape_cell(dtype)}` | "
                f"{mc} ({mr_pct}) | "
                f"`{_md_escape_cell(samples_short)}` | "
                f"{_md_escape_cell(sem_cell)} | "
                f"{_md_escape_cell(rag_cell)} |"
            )
            lines.append(row)

    warnings = fr.get("warnings") or []
    lines.append("")
    lines.append(f"## Warnings ({len(warnings)})")
    lines.append("")
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("_(none)_")

    evidence = src.get("evidence") or []
    lines.append("")
    lines.append(f"## Source evidence ({len(evidence)})")
    lines.append("")
    if evidence:
        for e in evidence:
            lines.append(f"- {e}")
    else:
        lines.append("_(none)_")

    # ── Synthèse — generated from facts, prevents LLM hallucination ────────
    lines.append("")
    lines.append("## Synthèse")
    lines.append("")
    file_path = fr.get("file_path", "unknown")
    file_name = file_path.rsplit("/", 1)[-1] if isinstance(file_path, str) and "/" in file_path else str(file_path)
    fmt_val = fr.get("format", "unknown")
    n_rows = fr.get("n_rows", "unknown")
    n_cols = fr.get("n_columns", "unknown")
    lines.append(f"- **Fichier** : `{file_name}` — format `{fmt_val}`, {n_rows} lignes × {n_cols} colonnes.")
    src_val = src.get("value", "unknown")
    src_conf = src.get("confidence", "low")
    lines.append(f"- **Source détectée** : `{src_val}` (confiance : `{src_conf}`).")
    missing_cols = [c for c in cols if isinstance(c.get("missing_rate"), (int, float)) and c.get("missing_rate", 0) > 0.3]
    if missing_cols:
        names = ", ".join(f"`{c['name']}`" for c in missing_cols[:5])
        suffix = "" if len(missing_cols) <= 5 else f" (+{len(missing_cols) - 5} autres)"
        lines.append(f"- **Colonnes >30% manquant** : {len(missing_cols)} — {names}{suffix}.")
    else:
        lines.append("- **Données manquantes** : aucune colonne au-dessus de 30%.")
    rag_count = len(column_definitions or [])
    if rag_count:
        lines.append(f"- **Définitions RAG** : {rag_count} colonnes documentées (voir table).")
    else:
        lines.append("- **Définitions RAG** : aucune colonne trouvée dans le corpus.")
    if warnings:
        lines.append(f"- **Avertissements** : {len(warnings)}.")
    lines.append("")
    lines.append("_Rapport complet ci-dessus. Le contenu est intégral — aucune troncature._")

    return chr(10).join(lines)


def summarize_understanding(inspect_report, role_report, column_definitions=None):
    """Produce the structured data understanding summary for Mode Plan.

    Call this after inspect_file, infer_column_roles, and all describe_column
    calls. The output is the documented snapshot the agent uses to lock in
    context before generating a graph.

    Does not decide which graph to produce. Does not interpret biologically.

    Args:
        inspect_report (dict): Output from inspect_file.
        role_report (dict): Output from infer_column_roles.
        column_definitions (list, optional): List of describe_column results,
            each a dict with keys: column, definition, unit, confidence,
            critical_notes, rag_doc_ref.

    Returns:
        dict: Structured summary for Mode Plan, including enriched column
            catalogue for use in graph generation.
    """
    quality_limits = []
    missing_or_ambiguous = []
    possible_joins = []

    # Quality limits from column missing rates
    for col in inspect_report.get("columns", []):
        rate = col.get("missing_rate", 0)
        if isinstance(rate, float) and rate > 0.3:
            quality_limits.append(
                f"Column '{col['name']}' has {round(rate * 100)}% missing values."
            )

    # Warnings from both reports
    for w in inspect_report.get("warnings", []) + role_report.get("warnings", []):
        missing_or_ambiguous.append(w)

    # Taxonomic validation status
    tax_val = "not_applicable"
    roles = role_report.get("roles", [])
    role_names = [r["role"] for r in roles]
    if "taxonomic_validation_status" in role_names:
        tax_val = "available"
    elif "taxon" in role_names:
        tax_val = "missing"

    # Columns with a role from pattern matching
    role_columns = [r["column"] for r in roles]

    # Columns resolved via RAG (describe_column)
    defs = column_definitions or []
    rag_columns = [d["column"] for d in defs if isinstance(d, dict) and d.get("column")]

    # All known columns = role-matched + RAG-defined
    all_known = list(dict.fromkeys(role_columns + rag_columns))

    # Remaining unmatched (neither pattern nor RAG covered them)
    unmatched = role_report.get("unmatched_columns", [])
    still_unknown = [c for c in unmatched if c not in rag_columns]
    if still_unknown:
        missing_or_ambiguous.append(
            f"Columns with no known definition: {', '.join(still_unknown[:10])}"
        )

    # Possible joins
    if "profile_id" in role_names:
        possible_joins.append("EcoPart join via profile_id (e.g. ips_007_899 → ips_007)")
    if "image_id" in role_names and "depth" in role_names:
        possible_joins.append("EcoTaxa ↔ EcoPart join via obj_orig_id → profile_id")

    source_guess = inspect_report.get("source_type_guess", {})

    supported_formats = {"csv", "tsv", "xlsx", "netcdf", "json"}
    file_format = inspect_report.get("format", "unknown")
    structural_signals = []
    semantic_signals = []
    coverage_gaps = []

    if file_format in supported_formats:
        structural_signals.append(f"format:{file_format}")
    if file_format in {"csv", "tsv"}:
        if inspect_report.get("metadata", {}).get("encoding"):
            structural_signals.append("encoding")
        if inspect_report.get("metadata", {}).get("delimiter"):
            structural_signals.append("delimiter")
    elif file_format == "xlsx":
        if inspect_report.get("metadata", {}).get("sheet_names"):
            structural_signals.append("sheet_names")
    elif file_format == "netcdf":
        if inspect_report.get("metadata", {}).get("netcdf_dimensions"):
            structural_signals.append("netcdf_dimensions")
        if inspect_report.get("metadata", {}).get("netcdf_variables"):
            structural_signals.append("netcdf_variables")
    elif file_format == "json":
        structural_signals.append("json_structure")

    if inspect_report.get("columns"):
        structural_signals.append(f"columns:{len(inspect_report.get('columns') or [])}")
    if source_guess.get("value") and source_guess.get("value") != "unknown":
        semantic_signals.append(f"source_type:{source_guess.get('value')}")
    if roles:
        semantic_signals.append(f"roles:{len(roles)}")
    if defs:
        semantic_signals.append(f"rag_definitions:{len(defs)}")

    # Build enriched column catalogue for graph generation
    column_catalogue = []
    role_map = {r["column"]: r for r in roles}
    rag_map = {d["column"]: d for d in defs if isinstance(d, dict) and d.get("column")}
    for col_name in all_known:
        entry = {"column": col_name}
        if col_name in role_map:
            entry["role"] = role_map[col_name]["role"]
            entry["role_confidence"] = role_map[col_name]["confidence"]
        if col_name in rag_map:
            rag = rag_map[col_name]
            entry["definition"] = rag.get("definition")
            entry["unit"] = rag.get("unit")
            entry["rag_confidence"] = rag.get("confidence")
            if rag.get("critical_notes"):
                entry["critical_notes"] = rag["critical_notes"]
        column_catalogue.append(entry)

    if file_format == "unknown":
        coverage_gaps.append("unsupported_or_unparsed_format")
    if file_format in supported_formats and not structural_signals:
        coverage_gaps.append("no_structural_signals_detected")
    if not all_known:
        coverage_gaps.append("no_useful_columns_identified")
    if not column_catalogue:
        coverage_gaps.append("no_column_catalogue_built")
    if source_guess.get("value", "unknown") == "unknown":
        coverage_gaps.append("source_type_unknown")

    if file_format == "unknown" or "unsupported_or_unparsed_format" in coverage_gaps:
        coverage_status = "insufficient"
    elif column_catalogue and semantic_signals:
        coverage_status = "sufficient"
    else:
        coverage_status = "partial"

    return {
        "file_or_source": inspect_report.get("file_path", "unknown"),
        "probable_source_type": source_guess.get("value", "unknown"),
        "useful_columns": all_known,
        "column_catalogue": column_catalogue,
        "metadata_detected": inspect_report.get("metadata", {}),
        "quality_limits": quality_limits,
        "taxonomic_validation_status": tax_val,
        "possible_joins_or_couplings": possible_joins,
        "missing_or_ambiguous_data": missing_or_ambiguous,
        "coverage_assessment": {
            "status": coverage_status,
            "format": file_format,
            "structural_signals": structural_signals,
            "semantic_signals": semantic_signals,
            "gaps": coverage_gaps,
        },
    }


def inspect_and_report(file_paths, session_id=None):
    """Inspect multiple files and return formatted reports + a cross-file summary.

    Encapsulates inspect_file + collect_column_definitions + format_inspect_report
    for every file in one atomic call. Use this instead of calling each step
    manually to avoid partial execution or hallucinated output.

    Args:
        file_paths (list[str]): Paths to files to inspect.
        session_id (str, optional): Session ID for RAG calls.

    Returns:
        dict: {
            "reports": list of {
                "file": str,          # short filename
                "formatted": str,     # full markdown report (or None on error)
                "source_type": str,   # source_type_guess value
                "n_rows": int,
                "n_columns": int,
                "error": str | None,  # None on success
            },
            "summary": str,           # short cross-file synthesis
        }
    """
    import pathlib

    reports = []
    for fp in file_paths:
        short = pathlib.Path(fp).stem
        # Step 1 — inspect (errors here are fatal for this file)
        try:
            file_report = inspect_file(fp)
            warnings_list = file_report.get("warnings") or []
            if any("not found" in w.lower() for w in warnings_list):
                raise FileNotFoundError(f"File not found: {fp}")
        except Exception as exc:
            reports.append({
                "file": short,
                "formatted": None,
                "source_type": "unknown",
                "n_rows": 0,
                "n_columns": 0,
                "error": str(exc),
            })
            continue

        # Step 2 — RAG enrichment (optional — failure yields empty defs)
        try:
            defs = collect_column_definitions(file_report, session_id=session_id)
        except Exception:
            defs = []

        # Step 3 — format report
        try:
            formatted = format_inspect_report(file_report, column_definitions=defs)
        except Exception as exc:
            reports.append({
                "file": short,
                "formatted": None,
                "source_type": "unknown",
                "n_rows": 0,
                "n_columns": 0,
                "error": str(exc),
            })
            continue

        source_type = (file_report.get("source_type_guess") or {}).get("value", "unknown")
        reports.append({
            "file": short,
            "formatted": formatted,
            "source_type": source_type,
            "n_rows": file_report.get("n_rows", 0),
            "n_columns": file_report.get("n_columns", 0),
            "error": None,
        })

    # Cross-file summary — scientific synthesis per file
    _source_labels = {
        "likely_ecotaxa": "export EcoTaxa (images + taxonomie annotée)",
        "likely_ecopart": "export EcoPart (profils CTD + particules agrégées)",
        "likely_neolabs_taxon": "données labo NeoLab (abondances zooplancton)",
        "likely_amundsen_ctd": "données CTD Amundsen / variables environnementales",
        "likely_environmental_model": "données modèle environnemental (Bio-Oracle / scénarios SSP)",
    }

    summary_lines = []
    for r in reports:
        if r["error"]:
            summary_lines.append(f"**{r['file']}** — erreur : {r['error']}")
            continue

        label = _source_labels.get(r["source_type"], r["source_type"])
        shape = f"{r['n_rows']} lignes × {r['n_columns']} colonnes"

        # Semantic columns present
        file_report = None
        for fp in file_paths:
            import pathlib
            if pathlib.Path(fp).stem == r["file"]:
                try:
                    file_report = inspect_file(fp)
                except Exception:
                    pass
                break

        sem_cols = []
        missing_flags = []
        warnings_list = []
        if file_report:
            for col in (file_report.get("columns") or []):
                sem = col.get("semantic_guess") or ""
                if sem and sem not in sem_cols:
                    sem_cols.append(sem)
                rate = col.get("missing_rate", 0)
                if isinstance(rate, float) and rate > 0.3:
                    missing_flags.append(f"`{col['name']}` ({round(rate*100)}% manquant)")
            warnings_list = file_report.get("warnings") or []

        sem_str = ", ".join(sem_cols[:5]) if sem_cols else "—"
        entry_lines = [f"**{r['file']}** ({shape}) — {label}"]
        entry_lines.append(f"  Variables : {sem_str}")
        for flag in missing_flags[:3]:
            entry_lines.append(f"  ⚠ {flag}")
        summary_lines.append(chr(10).join(entry_lines))

    # Cross-file join hints — only real oceanographic link keys, not any common column
    _VALID_JOIN_KEYS = {"PROFILE_ID", "OBJ_ORIG_ID", "OBJECT_ID", "PROFILEID"}
    all_cols = set()
    join_hints = []
    for r in reports:
        if not r["error"] and r.get("formatted"):
            for fp in file_paths:
                import pathlib
                if pathlib.Path(fp).stem == r["file"]:
                    try:
                        fr = inspect_file(fp)
                        cols = {c["name"].upper() for c in (fr.get("columns") or [])}
                        if all_cols:
                            common = (all_cols & cols) & _VALID_JOIN_KEYS
                            if common:
                                join_hints.append(", ".join(sorted(common)))
                        all_cols |= cols
                    except Exception:
                        pass
                    break

    if join_hints:
        summary_lines.append(f"Clés de jointure potentielles : {' | '.join(join_hints[:2])}")

    summary = chr(10).join(summary_lines)

    full_output = []
    for r in reports:
        if r["formatted"]:
            full_output.append(r["formatted"])
        else:
            full_output.append(f"## {r['file']} — ERREUR: {r['error']}")

    bullet_lines = ["- " + line for line in summary_lines]
    summary_md = "### Fichiers chargés" + chr(10) + chr(10) + (chr(10) + chr(10)).join(bullet_lines)

    full_output.append("%%SUMMARY%%")
    full_output.append(summary_md)
    full_output.append("%%CLOSING%%")
    full_output.append("Quel graphique ou livrable souhaitez-vous ?")

    return {"reports": reports, "summary": summary, "output": chr(10).join(full_output)}
'''

registry.register(Tool(
    name="copepod_data",
    tags=frozenset({"copepod_data"}),
    code=_code
))
