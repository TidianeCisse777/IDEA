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
            df_profile = df_sample

            try:
                df_full = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                      skiprows=skip_rows, on_bad_lines="skip",
                                      engine="python", usecols=lambda c: True)
                result["n_rows"] = len(df_full)
                df_profile = _distributed_profile_sample(df_full, sample_rows)
            except Exception:
                result["n_rows"] = f">{sample_rows} (sample only)"

            result["n_columns"] = len(df_profile.columns)
            result["columns"] = _describe_columns(df_profile)
            result["source_type_guess"] = _guess_source_type(df_profile.columns.tolist(), {"filename": path.stem})

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


def _distributed_profile_sample(df, max_rows):
    """Sample rows across the full dataframe instead of only the file head."""
    if not max_rows or len(df) <= max_rows:
        return df

    if max_rows == 1:
        return df.iloc[[0]]

    last_index = len(df) - 1
    step = last_index / (max_rows - 1)
    indices = []
    seen = set()
    for i in range(max_rows):
        idx = round(i * step)
        if idx not in seen:
            indices.append(idx)
            seen.add(idx)
    return df.iloc[indices]


def _semantic_guess(col_name, series):
    """Heuristic semantic guess from column name. Token-based to avoid false
    positives (e.g. previously ``sampling_platform`` matched ``"lat"`` via
    substring and was tagged as latitude).

    Confidence levels:
    - ``high``   : the token pattern is strongly diagnostic (``_id`` suffix,
                   ``year`` token, etc.)
    - ``medium`` : plausible from the name but the LLM should still check the
                   samples
    - ``low``    : weak signal — only useful as a hint
    """
    import re as _re
    name = col_name.lower()
    tokens = [t for t in _re.split(r'[ \t_/-]+', name) if t]

    def _has_token(*candidates):
        return any(t in tokens for t in candidates)

    def _ends_with(*suffixes):
        return any(name.endswith(s) for s in suffixes)

    def _starts_with(*prefixes):
        return any(name.startswith(p) for p in prefixes)

    # ── Identifiers ────────────────────────────────────────────────────────
    if _ends_with("_id", "_ids", "_identifier") or name in ("id", "ids"):
        return "identifier", None, "high"

    # ── Time / dates ───────────────────────────────────────────────────────
    if _has_token("datetime", "timestamp"):
        return "datetime", None, "high"
    if _has_token("date"):
        return "date", None, "high"
    if _has_token("year", "yr"):
        return "year", None, "high"
    if _has_token("month"):
        return "month", None, "high"
    if _has_token("day", "doy"):
        return "day", None, "high"
    if _has_token("time"):
        return "time", None, "medium"

    # ── Freetext / counts ──────────────────────────────────────────────────
    if _has_token("comment", "comments", "note", "notes", "remark", "remarks",
                  "description", "label"):
        return "freetext", None, "high"
    if _starts_with("number_of_", "nb_", "n_of_") or _has_token("count"):
        return "count", None, "high"

    # ── Geo ────────────────────────────────────────────────────────────────
    if _has_token("lat", "latitude"):
        return "latitude", "degrees", "high"
    if _has_token("lon", "long", "longitude"):
        return "longitude", "degrees", "high"
    if _has_token("abundance", "abund"):
        return "abundance", "ind/m3", "medium"
    if _has_token("temperature", "degc", "te90"):
        return "temperature", "degC", "medium"
    if _has_token("salinity", "psal", "psu"):
        return "salinity", "PSU", "medium"
    if _has_token("oxygen", "oxym", "um"):
        return "oxygen", "uM", "medium"
    if _has_token("fluorescence", "fluor", "flor", "ug", "chl"):
        return "fluorescence", "ug/L", "medium"
    if _has_token("nitrate", "ntra", "mmol", "no3"):
        return "nitrate", "mmol/m3", "medium"
    if _has_token("depth", "profondeur"):
        return "depth", "m", "medium"

    # ── Sampling / instruments ─────────────────────────────────────────────
    if _has_token("subsampling", "subsample", "fraction"):
        return "subsampling", None, "medium"
    if _has_token("mesh", "aperture"):
        return "mesh_specification", "µm or m", "medium"
    if _has_token("gear", "tow"):
        return "sampling_gear", None, "medium"
    if _has_token("platform", "vessel", "ship"):
        return "platform_label", None, "medium"
    if _has_token("protocol", "method"):
        return "protocol_label", None, "medium"
    if _has_token("contract"):
        return "contract_label", None, "medium"
    if _has_token("type", "category"):
        return "category_label", None, "medium"

    # ── Taxonomy ───────────────────────────────────────────────────────────
    if _has_token("taxon", "taxonom", "species", "classif"):
        return "taxon", None, "medium"
    if _has_token("valid"):
        return "taxonomic_validation_status", None, "medium"

    # ── Volumes / size / images ────────────────────────────────────────────
    if _has_token("vol", "volume"):
        return "sample_volume", "L or m3", "low"
    if _has_token("img", "image", "obj"):
        return "image_id", None, "low"
    if _has_token("station", "sta"):
        return "station", None, "medium"
    if _has_token("profile"):
        return "profile_id", None, "medium"
    if _has_token("pixel", "area", "esd", "major", "minor"):
        return "size_or_morphometry", "pixels or mm", "low"

    # ── Boolean-looking flags ──────────────────────────────────────────────
    if _ends_with("_flag", "_status") or _has_token("flag", "status"):
        return "flag", None, "medium"

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
    nicely when included in an assistant text reply: H1 title, compact header
    lines, a dedicated RAG definition section, an explicit section for
    columns the RAG does NOT cover, a compact columns table, warnings and
    source evidence as bullet lists. Every column appears — no truncation,
    no ellipsis.

    When ``column_definitions`` is provided (list of describe_column results,
    e.g. from ``collect_column_definitions``), the matching RAG definitions are
    rendered in a separate section above the table so they are easier to scan.
    Columns not present in ``column_definitions`` are surfaced in a dedicated
    "Colonnes sans définition RAG" section so the LLM can either interpret
    them or ask the user — they no longer disappear silently.

    Args:
        file_report (dict): The dict returned by ``inspect_file``.
        column_definitions (list[dict], optional): RAG definitions per column.

    Returns:
        str: Markdown text rendering of the full report.
    """
    import html as _html
    import re as _re

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

    def _group_definitions(column_name, column_meta=None):
        """Return a deterministic display group for a column definition."""
        column_meta = column_meta or {}
        semantic = str(column_meta.get("semantic_guess") or "").lower()
        normalized = _re.sub(r"[^a-z0-9]+", "_", str(column_name).lower()).strip("_")

        if semantic in {"taxon", "time", "station", "image_id", "depth", "latitude", "longitude"}:
            if semantic == "time":
                return "Dates / temps"
            if semantic == "taxon":
                return "Taxonomie"
            if semantic == "station" or semantic == "image_id":
                return "Identifiants"
            return "Mesures"

        if any(token in normalized for token in ("taxon", "class", "order", "family", "phylum", "kingdom", "species", "valid")):
            return "Taxonomie"
        if any(token in normalized for token in ("date", "time", "timestamp", "year", "month", "day", "hour", "minute", "second")):
            return "Dates / temps"
        # Mesures BEFORE Identifiants: prevents "sample" inside a measurement name
        # (e.g. amundsen_fluorescence_ug_l_max_sample_interval) from landing in Identifiants.
        # Short ERDDAP codes (ntra, flor, oxym) excluded — covered by full words and ambiguous as substrings.
        if any(token in normalized for token in (
            "depth", "vol", "mass", "size", "count", "abundance", "length", "width",
            "temperature", "salinity", "flow", "mesh", "fraction",
            "fluorescence", "oxygen", "nitrate", "sigma", "density", "pressure",
            "nearest", "interval",
        )):
            return "Mesures"
        # "sample" removed — covered by "id" for SAMPLE_ID / SAMPLING_NET_ID.
        if any(token in normalized for token in ("id", "name", "contract", "cast", "analysis", "station", "deployment", "file", "project")):
            return "Identifiants"
        return "Contexte / autres"

    def _render_definition_card(column_name, definition):
        rag_conf = _html.escape(str(definition.get("confidence", "unknown")))
        doc = _html.escape(str(definition.get("rag_doc_ref") or definition.get("source_file") or "RAG"))
        unit = definition.get("unit")
        unit_badge = f'<span class="definition-badge">unit: {_html.escape(str(unit))}</span>' if unit else ""
        text = _html.escape(str(definition.get("definition") or "").strip())
        name = _html.escape(str(column_name))
        notes = definition.get("critical_notes") or []
        notes_text = ""
        if notes:
            note_values = " ".join(f"[!] {_html.escape(str(note))}" for note in notes[:2])
            notes_text = f'<div class="definition-notes">{note_values}</div>'
        return (
            '<div class="definition-card">'
            f'<div class="definition-card-name">{name}</div>'
            f'<div class="definition-card-text">{text}</div>'
            f'<div class="definition-card-meta">'
            f'<span class="definition-badge">conf: {rag_conf}</span>'
            f'<span class="definition-badge">src: {doc}</span>'
            f"{unit_badge}"
            '</div>'
            f"{notes_text}"
            '</div>'
        )

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

    grouped_defs = {
        "Identifiants": [],
        "Dates / temps": [],
        "Mesures": [],
        "Taxonomie": [],
        "Contexte / autres": [],
    }
    cols_by_name = {str(c.get("name", "")): c for c in fr.get("columns") or []}
    for col_name in sorted(defs_by_col):
        group = _group_definitions(col_name, cols_by_name.get(col_name))
        grouped_defs.setdefault(group, []).append((col_name, defs_by_col[col_name]))

    lines.append("")
    lines.append(f"## Définitions détectées ({len(defs_by_col)})")
    lines.append("")
    if defs_by_col:
        for group_name in ["Identifiants", "Dates / temps", "Mesures", "Taxonomie", "Contexte / autres"]:
            group_items = grouped_defs.get(group_name) or []
            lines.append(f"### {group_name} ({len(group_items)})")
            lines.append("")
            if group_items:
                lines.append('<div class="definition-group">')
                for col_name, definition in group_items:
                    lines.append(_render_definition_card(col_name, definition))
                lines.append('</div>')
                lines.append("")
            else:
                lines.append("_(aucune colonne classée dans ce groupe)_")
                lines.append("")
    else:
        lines.append("_(aucune définition RAG trouvée)_")

    cols = fr.get("columns") or []

    # ── Layered confidence view — RAG > Auto-resolved > Needs clarification ─
    # The previous single "Colonnes sans définition RAG" section framed
    # everything outside the RAG as a problem the LLM had to solve. In
    # practice most of those columns are auto-evident from name + dtype +
    # samples (e.g. `*_id`, `*_year`, `*_comments`). Splitting them in two
    # tells the LLM "you already have grounding for N/M of these, focus
    # questions only on the truly ambiguous ones".
    #
    # Confidence tiers come from _semantic_guess:
    #   - high   → auto-resolved (use directly, document the assumption)
    #   - medium → auto-resolved (use, document the assumption, lighter prior)
    #   - low / None → needs clarification (ask the user if used downstream)
    undefined_cols = [c for c in cols if str(c.get("name", "")) not in defs_by_col]
    auto_resolved_cols: list = []
    need_clarif_cols: list = []
    for c in undefined_cols:
        sem = c.get("semantic_guess")
        conf = str(c.get("confidence", "low")).lower()
        if sem and conf in ("high", "medium"):
            auto_resolved_cols.append(c)
        else:
            need_clarif_cols.append(c)

    def _render_undefined_row(idx: int, c: dict) -> str:
        name = str(c.get("name", ""))
        dtype = str(c.get("dtype", ""))
        sem = c.get("semantic_guess")
        unit = c.get("unit_guess")
        conf = c.get("confidence", "low")
        if sem:
            sem_cell = f"`{sem}` ({conf})"
            if unit:
                sem_cell = f"{sem_cell} unit=`{unit}`"
        else:
            sem_cell = "—"
        samples = c.get("sample_values") or []
        samples_short = samples[:3]
        return (
            f"| {idx} | `{_md_escape_cell(name)}` | `{_md_escape_cell(dtype)}` | "
            f"{_md_escape_cell(sem_cell)} | "
            f"`{_md_escape_cell(samples_short)}` |"
        )

    lines.append("")
    lines.append(f"## Colonnes auto-résolues ({len(auto_resolved_cols)})")
    lines.append("")
    if not auto_resolved_cols:
        lines.append("_(aucune colonne auto-résolue par heuristique)_")
    else:
        lines.append(
            "Inférées du nom + dtype + samples. Confiance high/medium — "
            "utilisables directement; documenter l'assumption d'utilisation "
            "dans le plan. Pas besoin de question utilisateur pour ces colonnes."
        )
        lines.append("")
        lines.append("| # | Column | Dtype | Inferred semantic | Samples |")
        lines.append("|---|--------|-------|-------------------|---------|")
        for idx, c in enumerate(auto_resolved_cols, start=1):
            lines.append(_render_undefined_row(idx, c))

    lines.append("")
    lines.append(f"## Colonnes à clarifier ({len(need_clarif_cols)})")
    lines.append("")
    if not need_clarif_cols:
        lines.append("_(aucune colonne ambiguë restante)_")
    else:
        lines.append(
            "Pas de définition RAG et heuristique faible/absente. Si l'une "
            "de ces colonnes est nécessaire au calcul ou au graphe, poser "
            "une question numérotée à l'utilisateur (forme b du plan)."
        )
        lines.append("")
        lines.append("| # | Column | Dtype | Semantic hint | Samples |")
        lines.append("|---|--------|-------|---------------|---------|")
        for idx, c in enumerate(need_clarif_cols, start=1):
            lines.append(_render_undefined_row(idx, c))

    lines.append("")
    lines.append(f"## Columns ({len(cols)})")
    lines.append("")
    if not cols:
        lines.append("_(no columns parsed)_")
    else:
        lines.append("| # | Column | Dtype | Missing | Samples | Semantic |")
        lines.append("|---|--------|-------|---------|---------|----------|")
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

            row = (
                f"| {idx} | `{_md_escape_cell(name)}` | `{_md_escape_cell(dtype)}` | "
                f"{mc} ({mr_pct}) | "
                f"`{_md_escape_cell(samples_short)}` | "
                f"{_md_escape_cell(sem_cell)} |"
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

    # ── Synthèse — structured JSON, NOT French prose ──────────────────────
    # The previous prose synthesis ("Source détectée : likely_X (confiance :
    # high)", "Définitions RAG : 15 colonnes documentées, 18 sans définition")
    # was getting paraphrased verbatim by the LLM into user-visible responses.
    # JSON code-fence keeps the same facts available to the LLM as machine-
    # parsable data, but it does not read as a French summary the model can
    # recycle into prose. See docs/adr/006.
    import json as _json
    file_path = fr.get("file_path", "unknown")
    file_name = file_path.rsplit("/", 1)[-1] if isinstance(file_path, str) and "/" in file_path else str(file_path)
    missing_any = [c for c in cols if isinstance(c.get("missing_rate"), (int, float)) and c.get("missing_count", 0) > 0]
    worst_payload = None
    if missing_any:
        worst = max(
            missing_any,
            key=lambda c: c.get("missing_rate", 0) if isinstance(c.get("missing_rate"), (int, float)) else 0,
        )
        worst_payload = {
            "column": worst.get("name", "unknown"),
            "rate": worst.get("missing_rate", 0),
        }
    synthese_payload = {
        "file": file_name,
        "format": fr.get("format", "unknown"),
        "n_rows": fr.get("n_rows", "unknown"),
        "n_columns": fr.get("n_columns", "unknown"),
        "source_type": src.get("value", "unknown"),
        "source_confidence": src.get("confidence", "low"),
        "missing": {
            "n_columns_with_missing": len(missing_any),
            "worst": worst_payload,
        },
        "column_grounding": {
            "rag_defined": len(column_definitions or []),
            "auto_resolved": len(auto_resolved_cols),
            "needs_clarification": len(need_clarif_cols),
            "unresolved": [str(c.get("name", "")) for c in need_clarif_cols],
        },
        "warnings": len(warnings),
    }
    lines.append("")
    lines.append("## Synthèse")
    lines.append("")
    lines.append("```json")
    lines.append(_json.dumps(synthese_payload, ensure_ascii=False, indent=2))
    lines.append("```")

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

        # Compute the list of truly unresolved columns (no RAG def + no
        # high/medium heuristic guess). Mirrors the categorisation in
        # format_inspect_report so the telemetry stays consistent.
        defs_by_col = {str(d.get("column", "")) for d in (defs or []) if d.get("definition")}
        _cols = file_report.get("columns") or []
        unresolved_columns: list[str] = []
        for _c in _cols:
            _name = str(_c.get("name", ""))
            if not _name or _name in defs_by_col:
                continue
            _sem = _c.get("semantic_guess")
            _conf = str(_c.get("confidence", "low")).lower()
            if not (_sem and _conf in ("high", "medium")):
                unresolved_columns.append(_name)

        reports.append({
            "file": short,
            "formatted": formatted,
            "source_type": source_type,
            "n_rows": file_report.get("n_rows", 0),
            "n_columns": file_report.get("n_columns", 0),
            "unresolved_columns": unresolved_columns,
            "error": None,
        })

        # Store structured file_report so graph_readiness / resolve can auto-fetch
        # without requiring the caller to pass the full dict.
        try:
            import os as _os2
            from core.session_store import session_store as _store2
            _sk2 = _os2.environ.get("IDEA_RUNTIME_SESSION_KEY") or session_id
            if _sk2:
                _store2.store_inspection_data(_sk2, short, file_report)
        except Exception:
            pass

    summary_lines = []
    for r in reports:
        if r["error"]:
            summary_lines.append(f"**{r['file']}** — erreur : {r['error']}")
        else:
            summary_lines.append(
                f"**{r['file']}** ({r['n_rows']} lignes × {r['n_columns']} colonnes) — {r['source_type']}"
            )
    summary = chr(10).join(summary_lines)

    full_output = []
    for r in reports:
        if r["formatted"]:
            full_output.append(r["formatted"])
        else:
            full_output.append(f"## {r['file']} — ERREUR: {r['error']}")
    result = {"reports": reports, "summary": summary, "output": chr(10).join(full_output)}
    try:
        import os as _os
        _sk = _os.environ.get("IDEA_RUNTIME_SESSION_KEY")
        from core.copepod_observability import trace_copepod_tool_call
        # Telemetry on truly unresolved columns — used to Pareto-harvest the
        # top-K most-frequent unknowns into the RAG. See docs/adr/006.
        unresolved_by_file = {
            r["file"]: r.get("unresolved_columns", []) or []
            for r in reports
            if r.get("unresolved_columns")
        }
        trace_copepod_tool_call(
            "inspect_and_report",
            session_key=_sk,
            input={"file_paths": file_paths},
            output={
                "n_files": len(reports),
                "n_errors": sum(1 for r in reports if r.get("error")),
                "unresolved_columns_by_file": unresolved_by_file,
                "n_unresolved_total": sum(len(v) for v in unresolved_by_file.values()),
                "files": [
                    {
                        "file": r["file"],
                        "source_type": r.get("source_type"),
                        "n_rows": r.get("n_rows"),
                        "n_columns": r.get("n_columns"),
                        "error": r.get("error"),
                    }
                    for r in reports
                ],
            },
        )
    except Exception:
        pass
    return result


def get_inspection_report(filename):
    """Fetch the full RAPPORT D'INSPECTION for a file from out-of-context storage.

    Inspection reports are NOT kept in the conversation history (this would
    cause the LLM to paraphrase them into user-visible prose). After
    `inspect_and_report` runs, the report is streamed to the user once and
    persisted out-of-band. To read the full report (shape, columns, RAG
    definitions, missingness, join hints) on a later turn, call this tool
    with the filename — the bare filename, not a path.

    Args:
        filename (str): The basename of the inspected file (e.g. "sample.csv").

    Returns:
        str: The full report markdown, or a short "not found" message.
    """
    import os as _os
    import pathlib as _pathlib

    _key = _os.environ.get("IDEA_RUNTIME_SESSION_KEY", "")
    if not _key:
        return "[get_inspection_report] No active session key — cannot resolve inspection store."

    _name = _pathlib.Path(str(filename or "").strip()).name
    if not _name:
        return "[get_inspection_report] Filename required."

    try:
        from core.session_store import session_store as _store
        report = _store.read_inspection_report(_key, _name)
    except Exception as exc:
        return f"[get_inspection_report] Failed to read store: {exc}"

    if not report:
        try:
            available = _store.list_inspection_reports(_key)
        except Exception:
            available = []
        hint = f" Available: {available}" if available else ""
        return f"[get_inspection_report] No report stored for {_name!r}.{hint}"
    return report


def _graph_readiness_column_names(file_report):
    return [
        str(c.get("name", ""))
        for c in (file_report or {}).get("columns", []) or []
        if isinstance(c, dict) and c.get("name") is not None
    ]


def _graph_readiness_defs_by_col(column_definitions):
    defs_by_col = {}
    for definition in column_definitions or []:
        if not isinstance(definition, dict):
            continue
        column = definition.get("column")
        if column is None:
            continue
        if definition.get("definition") or definition.get("unit") or definition.get("confidence"):
            defs_by_col[str(column)] = definition
    return defs_by_col


def _graph_readiness_meta_by_col(file_report):
    return {
        str(c.get("name", "")): c
        for c in (file_report or {}).get("columns", []) or []
        if isinstance(c, dict) and c.get("name") is not None
    }


def _graph_readiness_is_auto_resolved(column_meta):
    semantic = (column_meta or {}).get("semantic_guess")
    confidence = str((column_meta or {}).get("confidence", "low")).lower()
    return bool(semantic and confidence in {"high", "medium"})


def _graph_readiness_is_taxonomic_intent(user_request="", graph_type="", required_columns=None, file_report=None):
    required = {str(c) for c in (required_columns or []) if str(c).strip()}
    required_meta = [
        c for c in ((file_report or {}).get("columns") or [])
        if isinstance(c, dict) and str(c.get("name") or "") in required
    ]
    text = " ".join([
        str(user_request or ""),
        str(graph_type or ""),
        " ".join(str(c) for c in (required_columns or [])),
        " ".join(
            str((c or {}).get("semantic_guess") or "")
            for c in required_meta
        ),
    ]).lower()
    tax_tokens = (
        "taxon", "taxonomie", "taxonomic", "taxonomique", "species",
        "espece", "espèce", "annotation", "classification",
    )
    return any(token in text for token in tax_tokens)


def _graph_readiness_taxonomic_validation_request():
    question = (
        "Pour ce graphe, faut-il conserver uniquement les annotations au statut "
        "`confirmed`, ou inclure aussi les annotations non confirmees ?"
    )
    return {
        "type": "taxonomic_validation_policy",
        "question": question,
        "expected_answers": ["confirmed_only", "include_unconfirmed"],
        "required_for_next_step": True,
    }


def _graph_readiness_request(request_type, question, **extra):
    payload = {
        "type": request_type,
        "question": question,
        "required_for_next_step": True,
    }
    payload.update(extra)
    return payload


def graph_readiness(
    file_report=None,
    required_columns=None,
    column_definitions=None,
    user_request="",
    graph_type=None,
    validation_status=None,
    filename=None,
    session_id=None,
):
    """Validate graph inputs before producing a graph or graph-derived table.

    The helper does not choose the graph and does not interpret biology. It
    checks that the exact columns selected for the graph exist and are grounded
    either by RAG definitions or by high/medium inspection heuristics. Required
    unresolved columns and unknown taxonomic validation policy produce targeted
    clarification questions instead of letting the model draw an approximate
    graph.
    """
    # If the caller passed the markdown string from get_inspection_report() instead of
    # the structured dict, discard it — the structured report is fetched from session below.
    if isinstance(file_report, str):
        file_report = None

    if not file_report and filename:
        try:
            import os as _osgr
            from core.session_store import session_store as _store_gr
            _sk_gr = _osgr.environ.get("IDEA_RUNTIME_SESSION_KEY") or session_id
            if _sk_gr:
                file_report = _store_gr.read_inspection_data(_sk_gr, filename) or file_report
        except Exception:
            pass

    required = [str(c) for c in (required_columns or []) if str(c).strip()]
    available_columns = _graph_readiness_column_names(file_report)
    available_set = set(available_columns)
    meta_by_col = _graph_readiness_meta_by_col(file_report)
    defs_by_col = _graph_readiness_defs_by_col(column_definitions)

    missing_required = [col for col in required if col not in available_set]
    rag_defined_required = [col for col in required if col in defs_by_col]
    auto_resolved_required = [
        col for col in required
        if col not in defs_by_col and col in available_set and _graph_readiness_is_auto_resolved(meta_by_col.get(col))
    ]
    unresolved_required = [
        col for col in required
        if col not in defs_by_col and col in available_set and col not in auto_resolved_required
    ]

    assumptions = []
    for col in auto_resolved_required:
        meta = meta_by_col.get(col) or {}
        assumptions.append(
            f"`{col}` treated as `{meta.get('semantic_guess')}` from inspection heuristic "
            f"(confidence: {meta.get('confidence', 'unknown')})."
        )

    quality_limits = []
    for col in required:
        meta = meta_by_col.get(col) or {}
        missing_rate = meta.get("missing_rate")
        if isinstance(missing_rate, (int, float)) and missing_rate > 0:
            quality_limits.append(
                f"`{col}` has {round(float(missing_rate) * 100, 1)}% missing values."
            )

    clarification_questions = []
    clarification_requests = []
    if not required:
        # Column selection is the agent's responsibility — do not ask the user.
        # Proceed and flag the omission as a quality limit.
        quality_limits.append(
            "No required_columns passed to graph_readiness — column grounding skipped. "
            "Select exact column names from the inspection report before graphing."
        )
    if missing_required:
        avail_str = (
            ", ".join(f"`{col}`" for col in available_columns[:15])
            + ("…" if len(available_columns) > 15 else "")
            if available_columns else "aucune colonne détectée"
        )
        request = _graph_readiness_request(
            "missing_required_columns",
            "Les colonnes requises sont absentes du fichier inspecté: "
            + ", ".join(f"`{col}`" for col in missing_required)
            + f". Colonnes disponibles dans le fichier : {avail_str}"
            + ". Quelle colonne faut-il utiliser à la place ?",
            missing_columns=missing_required,
            available_columns_preview=available_columns[:15],
        )
        clarification_requests.append(request)
        clarification_questions.append(f"1. {request['question']}")
    if unresolved_required:
        request = _graph_readiness_request(
            "unresolved_required_columns",
            "Confirmez la signification de ces colonnes avant le graphe: "
            + ", ".join(f"`{col}`" for col in unresolved_required)
            + ".",
            unresolved_columns=unresolved_required,
        )
        clarification_requests.append(request)
        clarification_questions.append(f"1. {request['question']}")

    validation_value = str(validation_status or "").strip().lower()
    validation_unknown = validation_value in {"", "unknown", "ambiguous", "unconfirmed", "inconnu", "ambigu"}
    if _graph_readiness_is_taxonomic_intent(user_request, graph_type or "", required, file_report) and validation_unknown:
        request = _graph_readiness_taxonomic_validation_request()
        clarification_requests.append(request)
        clarification_questions.append(f"1. {request['question']}")

    ready = not clarification_questions
    return {
        "ready": ready,
        "status": "ready" if ready else "needs_clarification",
        "required_columns": required,
        "available_columns": available_columns,
        "rag_defined_required_columns": rag_defined_required,
        "auto_resolved_required_columns": auto_resolved_required,
        "unresolved_required_columns": unresolved_required,
        "missing_required_columns": missing_required,
        "validation_status": validation_status if validation_status is not None else "unknown",
        "assumptions": assumptions,
        "quality_limits": quality_limits,
        "clarification_questions": clarification_questions,
        "clarification_requests": clarification_requests,
        "recommended_next_step": (
            "proceed_with_graph" if ready else "ask_clarification_before_graph"
        ),
    }


def _normalized_join_key_series(df, key):
    if key not in df.columns:
        raise KeyError(f"Missing join key: {key}")
    return df[key].dropna().astype(str).str.strip()


def profile_join_keys(left, right, left_key, right_key):
    """Profile join cardinality and row expansion before building deliverables."""
    left_keys = _normalized_join_key_series(left, left_key)
    right_keys = _normalized_join_key_series(right, right_key)

    left_counts = left_keys.value_counts()
    right_counts = right_keys.value_counts()
    left_duplicate_keys = int((left_counts > 1).sum())
    right_duplicate_keys = int((right_counts > 1).sum())

    if left_duplicate_keys and right_duplicate_keys:
        cardinality = "many_to_many"
    elif left_duplicate_keys:
        cardinality = "many_to_one"
    elif right_duplicate_keys:
        cardinality = "one_to_many"
    else:
        cardinality = "one_to_one"

    left_unique = set(left_counts.index)
    right_unique = set(right_counts.index)
    matched_unique = left_unique & right_unique
    left_match_rate = round(len(matched_unique) / len(left_unique) * 100, 2) if left_unique else 0.0
    right_match_rate = round(len(matched_unique) / len(right_unique) * 100, 2) if right_unique else 0.0

    estimated_rows = 0
    for key in matched_unique:
        estimated_rows += int(left_counts[key]) * int(right_counts[key])
    row_expansion_factor = round(estimated_rows / len(left), 4) if len(left) else 0.0

    requires_aggregation = cardinality in {"one_to_many", "many_to_many"}
    safe_for_join_deliverable = (
        cardinality in {"one_to_one", "many_to_one"}
        and row_expansion_factor <= 1.05
    )

    profile = {
        "left_key": left_key,
        "right_key": right_key,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_unique_keys": int(len(left_unique)),
        "right_unique_keys": int(len(right_unique)),
        "matched_unique_keys": int(len(matched_unique)),
        "left_duplicate_keys": left_duplicate_keys,
        "right_duplicate_keys": right_duplicate_keys,
        "cardinality": cardinality,
        "left_match_rate": left_match_rate,
        "right_match_rate": right_match_rate,
        "estimated_join_rows": int(estimated_rows),
        "row_expansion_factor": row_expansion_factor,
        "requires_aggregation": requires_aggregation,
        "safe_for_join_deliverable": safe_for_join_deliverable,
    }
    _copepod_register_join_profile(left, right, left_key, right_key, profile)
    return profile


def emit_deliverable(type, title, summary=None, fields=None, file=None):
    """Emit one normalized DELIVERABLE payload for the UI card pipeline."""
    import json as _json

    payload = {
        "type": str(type),
        "title": str(title),
    }
    if summary is not None:
        payload["summary"] = str(summary)

    normalized_fields = []
    for item in fields or []:
        if not isinstance(item, dict):
            continue
        if "label" not in item or "value" not in item:
            continue
        normalized_fields.append({
            "label": str(item["label"]),
            "value": str(item["value"]),
        })
    if normalized_fields:
        payload["fields"] = normalized_fields

    if file is not None:
        payload["file"] = str(file)

    print("DELIVERABLE: " + _json.dumps(payload, ensure_ascii=False))
    return payload


_COPEPOD_JOIN_PROFILE_REGISTRY = {}
_COPEPOD_JOIN_GUARD_INSTALLED = False
_COPEPOD_ORIGINAL_DF_MERGE = None
_COPEPOD_ORIGINAL_PD_MERGE = None


def _copepod_join_signature(df, key):
    import hashlib
    import json

    series = _normalized_join_key_series(df, key)
    counts = series.value_counts(dropna=False)
    payload = sorted((str(idx), int(count)) for idx, count in counts.items())
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _copepod_register_join_profile(left, right, left_key, right_key, profile):
    registry_key = (
        _copepod_join_signature(left, left_key),
        _copepod_join_signature(right, right_key),
        str(left_key),
        str(right_key),
    )
    _COPEPOD_JOIN_PROFILE_REGISTRY[registry_key] = profile


def _copepod_lookup_join_profile(left, right, left_key, right_key):
    registry_key = (
        _copepod_join_signature(left, left_key),
        _copepod_join_signature(right, right_key),
        str(left_key),
        str(right_key),
    )
    return _COPEPOD_JOIN_PROFILE_REGISTRY.get(registry_key)


def _copepod_normalize_join_key_arg(value):
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise RuntimeError(
                "Join guard only supports a single explicit join key. "
                "Call profile_join_keys(left_df, right_df, left_key, right_key) "
                "with one key and merge on that same key."
            )
        return str(value[0])
    if value is None:
        return None
    return str(value)


def _copepod_guarded_df_merge(self, right, *args, **kwargs):
    left_on = _copepod_normalize_join_key_arg(kwargs.get("left_on"))
    right_on = _copepod_normalize_join_key_arg(kwargs.get("right_on"))
    on = _copepod_normalize_join_key_arg(kwargs.get("on"))
    if on is not None:
        left_on = left_on or on
        right_on = right_on or on
    if not left_on or not right_on:
        raise RuntimeError(
            "Call profile_join_keys(left_df, right_df, left_key, right_key) "
            "before merge. Explicit left_on/right_on keys are required."
        )

    profile = _copepod_lookup_join_profile(self, right, left_on, right_on)
    if not profile:
        raise RuntimeError(
            "Join blocked: call profile_join_keys(left_df, right_df, left_key, right_key) "
            "on the exact dataframes and keys you plan to merge, then read its output."
        )
    if not profile.get("safe_for_join_deliverable"):
        raise RuntimeError(
            "Join blocked: the profiled keys are not safe_for_join_deliverable "
            f"(cardinality={profile.get('cardinality')}, "
            f"row_expansion_factor={profile.get('row_expansion_factor')})."
        )
    return _COPEPOD_ORIGINAL_DF_MERGE(self, right, *args, **kwargs)


def _copepod_guarded_pd_merge(left, right, *args, **kwargs):
    left_on = _copepod_normalize_join_key_arg(kwargs.get("left_on"))
    right_on = _copepod_normalize_join_key_arg(kwargs.get("right_on"))
    on = _copepod_normalize_join_key_arg(kwargs.get("on"))
    if on is not None:
        left_on = left_on or on
        right_on = right_on or on
    if not left_on or not right_on:
        raise RuntimeError(
            "Call profile_join_keys(left_df, right_df, left_key, right_key) "
            "before pd.merge. Explicit left_on/right_on keys are required."
        )

    profile = _copepod_lookup_join_profile(left, right, left_on, right_on)
    if not profile:
        raise RuntimeError(
            "Join blocked: call profile_join_keys(left_df, right_df, left_key, right_key) "
            "on the exact dataframes and keys you plan to merge, then read its output."
        )
    if not profile.get("safe_for_join_deliverable"):
        raise RuntimeError(
            "Join blocked: the profiled keys are not safe_for_join_deliverable "
            f"(cardinality={profile.get('cardinality')}, "
            f"row_expansion_factor={profile.get('row_expansion_factor')})."
        )
    return _COPEPOD_ORIGINAL_PD_MERGE(left, right, *args, **kwargs)


def install_copepod_join_guard():
    global _COPEPOD_JOIN_GUARD_INSTALLED, _COPEPOD_ORIGINAL_DF_MERGE, _COPEPOD_ORIGINAL_PD_MERGE
    import pandas as pd

    if not hasattr(pd, "_copepod_original_dataframe_merge"):
        pd._copepod_original_dataframe_merge = pd.DataFrame.merge
    if not hasattr(pd, "_copepod_original_pd_merge"):
        pd._copepod_original_pd_merge = pd.merge

    _COPEPOD_ORIGINAL_DF_MERGE = pd._copepod_original_dataframe_merge
    _COPEPOD_ORIGINAL_PD_MERGE = pd._copepod_original_pd_merge
    pd.DataFrame.merge = _copepod_guarded_df_merge
    pd.merge = _copepod_guarded_pd_merge
    _COPEPOD_JOIN_GUARD_INSTALLED = True
    pd._copepod_join_guard_installed = True


install_copepod_join_guard()
'''

registry.register(Tool(
    name="copepod_data",
    tags=frozenset({"copepod_data"}),
    code=_code
))
