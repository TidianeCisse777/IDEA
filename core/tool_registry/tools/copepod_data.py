from core.tool_registry.registry import Tool, registry

_code = '''
def inspect_file(file_path, sample_rows=20):
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
        import pandas as pd
        import chardet

        with open(path, "rb") as f:
            raw = f.read(min(100_000, path.stat().st_size))
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        result["metadata"]["encoding"] = encoding

        delimiter = "\t" if suffix == ".tsv" else None
        try:
            df_sample = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                    nrows=sample_rows, on_bad_lines="skip",
                                    engine="python")
            result["metadata"]["delimiter"] = df_sample.attrs.get("sep", delimiter or "auto-detected")
            result["format"] = "tsv" if suffix == ".tsv" else "csv"

            try:
                df_full = pd.read_csv(path, sep=delimiter, encoding=encoding,
                                      on_bad_lines="skip", engine="python",
                                      usecols=lambda c: True)
                result["n_rows"] = len(df_full)
            except Exception:
                result["n_rows"] = f">{sample_rows} (sample only)"

            result["n_columns"] = len(df_sample.columns)
            result["columns"] = _describe_columns(df_sample)
            result["source_type_guess"] = _guess_source_type(df_sample.columns.tolist(), {})

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
    names_lower = [c.lower() for c in column_names]
    evidence = []
    scores = {"likely_ecotaxa": 0, "likely_ecopart": 0,
              "likely_amundsen_ctd": 0, "likely_lab_data": 0}

    ecotaxa_signals = ["classif_id", "classif_qual", "object_id", "obj_depth",
                       "acq_", "process_", "img_file", "object_lat", "object_lon"]
    ecopart_signals = ["profile_id", "nb_part", "volume_analyzed",
                       "depth_min", "depth_max", "biovolume"]
    ctd_signals = ["te90", "psal", "oxym", "fluo", "tur9", "sigt",
                   "latitude", "longitude", "station"]
    lab_signals = ["lipid", "carbon", "biomass", "drymass", "wax_ester",
                   "fatty_acid", "tl_", "dw_"]

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

    role_patterns = {
        "depth":                    ["depth", "profondeur"],
        "latitude":                 ["lat", "latitude"],
        "longitude":                ["lon", "longitude"],
        "time":                     ["time", "date", "datetime", "timestamp"],
        "taxon":                    ["classif_id", "classif_auto_id", "taxon", "taxonom", "species"],
        "taxonomic_validation_status": ["classif_qual", "valid"],
        "profile_id":               ["profile_id", "profileid", "profile"],
        "station":                  ["station", "sta_"],
        "sample_volume":            ["vol", "volume"],
        "image_id":                 ["object_id", "obj_id", "img_file", "image"],
        "pixel_calibration":        ["acq_pixel", "process_pixel"],
        "size_or_morphometry":      ["area", "esd", "major", "minor", "perimeter", "feret", "width", "height"],
        "environmental_variable":   ["te90", "psal", "oxym", "fluo", "temp", "sal", "oxygen"],
        "lab_measurement":          ["lipid", "carbon", "biomass", "wax", "fatty", "drymass"],
    }

    col_names = [c["name"] for c in columns] if columns and isinstance(columns[0], dict) else columns

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
        if not found and isinstance(columns[0], dict):
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


def summarize_understanding(inspect_report, role_report):
    """Produce the structured data understanding summary for Mode Plan.

    Call this after inspect_file and infer_column_roles (and optionally after
    querying the knowledge base). The output is the documented snapshot the
    agent uses to lock in context before generating a graph.

    Does not decide which graph to produce. Does not interpret biologically.

    Args:
        inspect_report (dict): Output from inspect_file.
        role_report (dict): Output from infer_column_roles.

    Returns:
        dict: Structured summary for Mode Plan.
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

    # Unmatched columns
    unmatched = role_report.get("unmatched_columns", [])
    if unmatched:
        missing_or_ambiguous.append(
            f"Unmatched columns (role unknown): {', '.join(unmatched[:10])}"
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

    # Useful columns (those with a matched role)
    useful_columns = [r["column"] for r in roles]

    # Possible joins
    if "profile_id" in role_names:
        possible_joins.append("EcoPart join via profile_id (e.g. ips_007_899 → ips_007)")
    if "image_id" in role_names and "depth" in role_names:
        possible_joins.append("EcoTaxa ↔ EcoPart join via obj_orig_id → profile_id")

    source_guess = inspect_report.get("source_type_guess", {})

    return {
        "file_or_source": inspect_report.get("file_path", "unknown"),
        "probable_source_type": source_guess.get("value", "unknown"),
        "useful_columns": useful_columns,
        "metadata_detected": inspect_report.get("metadata", {}),
        "quality_limits": quality_limits,
        "taxonomic_validation_status": tax_val,
        "possible_joins_or_couplings": possible_joins,
        "missing_or_ambiguous_data": missing_or_ambiguous
    }
'''

registry.register(Tool(
    name="copepod_data",
    tags=frozenset({"copepod_data"}),
    code=_code
))
