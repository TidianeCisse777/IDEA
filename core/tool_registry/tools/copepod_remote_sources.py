from core.tool_registry.registry import Tool, registry

_code = '''
def _remote_source_upload_root(session_key):
    from pathlib import Path
    from routers.file_routes import STATIC_DIR, UPLOAD_DIR

    parts = [part for part in str(session_key or "").split(":") if part]
    if len(parts) < 2:
        raise ValueError("session_key must be formatted as user_id:session_id:agent_type")
    user_id, session_id = parts[0], parts[1]
    return STATIC_DIR / user_id / session_id / UPLOAD_DIR


def _slugify_token(value, max_length=64):
    import re

    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_.-")
    return (text or "value")[:max_length]


def _unique_csv_path(root, basename):
    from pathlib import Path

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / basename
    if candidate.suffix.lower() != ".csv":
        candidate = candidate.with_suffix(".csv")
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(2, 1000):
        trial = root / f"{stem}_{idx}{suffix}"
        if not trial.exists():
            return trial
    raise RuntimeError(f"Unable to allocate a unique filename for {basename!r}")


def _extract_int_from_meta(meta_value):
    import re

    if not meta_value:
        return None
    match = re.search(r"nValues=(\\d+)", str(meta_value))
    return int(match.group(1)) if match else None


def _extract_float_attr(info_rows, attr_name):
    for row in info_rows:
        if len(row) >= 5 and row[0] == "attribute" and row[2] == attr_name:
            try:
                return float(row[4])
            except Exception:
                return None
    return None


def _extract_dimension_meta(info_rows, dimension_name):
    for row in info_rows:
        if len(row) >= 5 and row[0] == "dimension" and row[1] == dimension_name:
            return row[4]
    return None


def _extract_data_variables(info_rows):
    variables = []
    for row in info_rows:
        if len(row) >= 5 and row[0] == "variable":
            name = row[1]
            if name not in {"time", "latitude", "longitude"}:
                variables.append(name)
    return variables


def _choose_bio_oracle_dataset(rows, variable, scenario):
    requested = " ".join(
        part for part in [variable or "", scenario or ""] if part
    ).lower()
    best = None
    best_score = -1
    for row in rows:
        title = str(row.get("Title") or row.get("title") or "")
        dataset_id = str(row.get("Dataset ID") or row.get("Dataset_ID") or "")
        haystack = f"{title} {dataset_id}".lower()
        score = 0
        if requested and requested in haystack:
            score += 10
        if variable and variable.lower() in haystack:
            score += 5
        if scenario and scenario.lower() in haystack:
            score += 3
        if "bio-oracle" in haystack:
            score += 2
        if "griddap" in row and row.get("griddap"):
            score += 1
        if score > best_score:
            best = row
            best_score = score
    return best or (rows[0] if rows else None)


def _choose_ogsl_resource(packages, station=None, mission=None):
    search_terms = " ".join(part for part in [mission or "", station or "", "ctd"] if part).lower()
    for package in packages or []:
        resources = package.get("resources") or []
        for resource in resources:
            url = str(resource.get("url") or "")
            title = f"{package.get('title') or ''} {resource.get('name') or ''}".lower()
            haystack = f"{title} {url.lower()}"
            if "erddap.ogsl.ca/erddap/tabledap/" not in url and "catalogue.ogsl.ca/data/" not in url:
                continue
            if search_terms and any(term and term in haystack for term in search_terms.split()):
                return package, resource
            if "erddap.ogsl.ca/erddap/tabledap/" in url:
                return package, resource
    return None, None


def _add_ogsl_filters(url, parameters):
    from urllib.parse import quote

    period = parameters.get("period") or {}
    station = parameters.get("station")
    mission = parameters.get("mission")

    separators = "&" if "?" in url else "?"
    filters = []
    start = period.get("start")
    end = period.get("end")
    if start and "time>=" not in url and "time%3E%3D" not in url:
        filters.append(f"time>={quote(str(start))}")
    if end and "time<=" not in url and "time%3C%3D" not in url:
        filters.append(f"time<={quote(str(end))}")
    if station and "stationID" not in url:
        filters.append("stationID=" + quote('"' + str(station) + '"'))
    if mission and "cruiseID" not in url:
        filters.append("cruiseID=" + quote('"' + str(mission) + '"'))
    if filters:
        url = f"{url}{separators}{'&'.join(filters)}"
    return url


def _write_derived_csv(session_key, dataframe, base_name, metadata):
    import pandas as pd

    output_root = _remote_source_upload_root(session_key)
    output_path = _unique_csv_path(output_root, base_name)
    dataframe.to_csv(output_path, index=False)
    file_path_str = str(output_path)
    download_url = "/" + file_path_str.lstrip("/")
    return {
        "source_id": metadata.get("source_id"),
        "source_dataset_id": metadata.get("source_dataset_id"),
        "source_dataset_title": metadata.get("source_dataset_title"),
        "source_query": metadata.get("source_query"),
        "file_path": file_path_str,
        "download_url": download_url,
        "original_filename": output_path.name,
        "size_bytes": output_path.stat().st_size,
        "row_count": int(len(dataframe.index)),
        "columns": list(dataframe.columns),
        "status": "persisted",
    }


def _bio_oracle_fetch(session_key, parameters):
    import io
    import pandas as pd
    import requests

    variable = parameters.get("variable")
    variables = list(parameters.get("variables") or ([] if not variable else [variable]))
    scenario = parameters.get("scenario")
    period = parameters.get("period") or {}
    zone = parameters.get("zone") or {}
    latitude = zone.get("latitude", parameters.get("latitude"))
    longitude = zone.get("longitude", parameters.get("longitude"))

    missing = []
    if not scenario:
        missing.append("scenario")
    if not variables:
        missing.append("variable")
    if latitude is None or longitude is None:
        missing.append("zone")
    if missing:
        return {
            "source_id": "bio_oracle",
            "status": "needs_clarification",
            "missing_fields": missing,
            "clarification_question": "Quelle zone ou quelles coordonnées voulez-vous utiliser pour Bio-ORACLE ?",
        }

    search_url = "https://erddap.bio-oracle.org/erddap/search/index.json"
    search_candidates = [
        " ".join(part for part in [variables[0], scenario] if part),
        variables[0],
        scenario,
        "bio-oracle",
    ]
    search_terms = search_candidates[0]
    rows = []
    for candidate in search_candidates:
        if not candidate:
            continue
        search_terms = candidate
        try:
            search_resp = requests.get(
                search_url,
                params={"searchFor": candidate, "itemsPerPage": 20},
                timeout=30,
            )
            search_resp.raise_for_status()
        except Exception:
            continue
        search_table = (search_resp.json() or {}).get("table") or {}
        columns = search_table.get("columnNames") or []
        rows = [dict(zip(columns, row)) for row in (search_table.get("rows") or [])]
        if rows:
            break
    chosen = _choose_bio_oracle_dataset(rows, variables[0], scenario)
    if not chosen:
        raise RuntimeError("Bio-ORACLE dataset search returned no usable result")

    dataset_id = chosen.get("Dataset ID") or chosen.get("Dataset_ID")
    griddap_url = chosen.get("griddap")
    info_url = chosen.get("Info") or f"https://erddap.bio-oracle.org/erddap/info/{dataset_id}/index.json"
    info_resp = requests.get(info_url, timeout=30)
    info_resp.raise_for_status()
    info_rows = ((info_resp.json() or {}).get("table") or {}).get("rows") or []

    data_variables = _extract_data_variables(info_rows)
    requested_variable = variables[0]
    data_variable = next(
        (name for name in data_variables if name.lower() == requested_variable.lower()),
        data_variables[0] if data_variables else requested_variable,
    )
    n_time = _extract_int_from_meta(_extract_dimension_meta(info_rows, "time")) or 1
    lat_min = _extract_float_attr(info_rows, "geospatial_lat_min")
    lon_min = _extract_float_attr(info_rows, "geospatial_lon_min")
    lat_res = _extract_float_attr(info_rows, "geospatial_lat_resolution") or 0.05
    lon_res = _extract_float_attr(info_rows, "geospatial_lon_resolution") or 0.05
    if lat_min is None or lon_min is None:
        raise RuntimeError("Bio-ORACLE dataset metadata is missing the grid origin")

    lat_idx = round((float(latitude) - lat_min) / lat_res)
    lon_idx = round((float(longitude) - lon_min) / lon_res)
    lat_idx = max(0, min(3599, lat_idx))
    lon_idx = max(0, min(7199, lon_idx))

    query_url = f"{griddap_url}.csv?{data_variable}[0:1:{n_time - 1}][{lat_idx}:1:{lat_idx}][{lon_idx}:1:{lon_idx}]"
    query_resp = requests.get(query_url, timeout=30)
    query_resp.raise_for_status()
    dataframe = pd.read_csv(io.StringIO(query_resp.text))
    if "time" in dataframe.columns:
        dataframe["time"] = pd.to_datetime(dataframe["time"], errors="coerce", utc=True)
        start = period.get("start")
        end = period.get("end")
        if start or end:
            start_ts = pd.to_datetime(
                f"{start}-01-01"
                if isinstance(start, int) or (isinstance(start, str) and str(start).isdigit() and len(str(start)) == 4)
                else start,
                errors="coerce",
                utc=True,
            ) if start else None
            end_ts = pd.to_datetime(
                f"{end}-12-31"
                if isinstance(end, int) or (isinstance(end, str) and str(end).isdigit() and len(str(end)) == 4)
                else end,
                errors="coerce",
                utc=True,
            ) if end else None
            if start_ts is not None:
                dataframe = dataframe[dataframe["time"] >= start_ts]
            if end_ts is not None:
                dataframe = dataframe[dataframe["time"] <= end_ts]
    dataframe = dataframe.reset_index(drop=True)
    filename = "_".join(
        [
            "bio_oracle",
            _slugify_token(requested_variable),
            _slugify_token(scenario),
            _slugify_token(period.get("start") or "start"),
            _slugify_token(period.get("end") or "end"),
            f"lat{_slugify_token(latitude)}",
            f"lon{_slugify_token(longitude)}",
        ]
    )[:180] + ".csv"
    return _write_derived_csv(
        session_key,
        dataframe,
        filename,
        {
            "source_id": "bio_oracle",
            "source_dataset_id": dataset_id,
            "source_dataset_title": chosen.get("Title") or chosen.get("title"),
            "source_query": search_terms,
        },
    )


def _ogsl_fetch(session_key, parameters):
    import io
    import pandas as pd
    import requests

    station = parameters.get("station")
    mission = parameters.get("mission")
    period = parameters.get("period") or {}
    variables = list(parameters.get("variables") or [])
    search_terms = " ".join(
        part for part in [mission or "", station or "", "ctd"] if part
    ).strip() or "ctd"
    package_resp = requests.get(
        "https://catalogue.ogsl.ca/api/3/action/package_search",
        params={"q": search_terms},
        timeout=30,
    )
    package_resp.raise_for_status()
    package_payload = package_resp.json() or {}
    packages = ((package_payload.get("result") or {}).get("results") or [])
    package, resource = _choose_ogsl_resource(packages, station=station, mission=mission)
    if not package or not resource:
        raise RuntimeError("No OGSL tabular resource matched the request")

    resource_url = str(resource.get("url") or "")
    if ".html" in resource_url:
        resource_url = resource_url.replace(".html", ".csv")
    resource_url = _add_ogsl_filters(resource_url, parameters)
    data_resp = requests.get(resource_url, timeout=30)
    data_resp.raise_for_status()
    dataframe = pd.read_csv(io.StringIO(data_resp.text))

    if "time" in dataframe.columns and period:
        dataframe["time"] = pd.to_datetime(dataframe["time"], errors="coerce", utc=True)
        start = period.get("start")
        end = period.get("end")
        if start is not None:
            dataframe = dataframe[dataframe["time"] >= pd.to_datetime(start, errors="coerce", utc=True)]
        if end is not None:
            dataframe = dataframe[dataframe["time"] <= pd.to_datetime(end, errors="coerce", utc=True)]

    if variables:
        core_columns = [c for c in ["longitude", "latitude", "time", "cruiseID", "stationID", "cast_number"] if c in dataframe.columns]
        requested_columns = [c for c in variables if c in dataframe.columns and c not in core_columns]
        if core_columns or requested_columns:
            keep = core_columns + requested_columns
            dataframe = dataframe.loc[:, [c for c in keep if c in dataframe.columns]]

    dataframe = dataframe.reset_index(drop=True)
    filename = "_".join(
        [
            "ogsl",
            _slugify_token(mission or station or "ctd"),
            _slugify_token(period.get("start") or "start"),
            _slugify_token(period.get("end") or "end"),
        ]
    )[:180] + ".csv"
    return _write_derived_csv(
        session_key,
        dataframe,
        filename,
        {
            "source_id": "ogsl",
            "source_dataset_id": package.get("name") or package.get("id"),
            "source_dataset_title": package.get("title"),
            "source_query": search_terms,
        },
    )


def fetch_remote_source_dataset(session_key, source_id, parameters, output_filename=None):
    """Fetch an online source, persist it as a derived CSV in the session uploads folder.

    The tool keeps the raw remote source separate from the derived file. The
    derived file is written to the same session upload directory used for user
    uploads so it can be inspected and reused by the agent like any other file.
    """
    from core.copepod_observability import trace_copepod_event

    params = dict(parameters or {})
    source_key = str(source_id or "").strip().lower()

    if source_key == "bio_oracle":
        result = _bio_oracle_fetch(session_key, params)
    elif source_key == "ogsl":
        result = _ogsl_fetch(session_key, params)
    else:
        result = {
            "source_id": source_key or "unknown",
            "status": "needs_clarification",
            "missing_fields": ["source_id"],
            "clarification_question": "Quelle source voulez-vous utiliser, OGSL ou Bio-ORACLE ?",
        }

    if result.get("status") == "persisted":
        trace_copepod_event(
            "remote_source_dataset_fetched",
            session_key=session_key or "",
            output=result,
        )
    else:
        trace_copepod_event(
            "remote_source_dataset_fetch_blocked",
            session_key=session_key or "",
            output=result,
        )
    return result
'''

registry.register(Tool(
    name="copepod_remote_sources",
    tags=frozenset({"copepod_remote_sources"}),
    code=_code,
))
