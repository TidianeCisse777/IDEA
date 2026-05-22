from core.tool_registry.registry import Tool, registry

_code = '''def get_climate_index(climate_index_name: str) -> pd.DataFrame:
    \'\'\'Load climate indices into a tidy DataFrame with columns (time, value).

    Notes
    -----
    - This version updates ONI to use CPC\'s ONI seasonal product (3-month means)
      and adds CPC\'s Relative ONI (RONI).
    - Timestamps for ONI/RONI represent the *middle month* of each 3-month season,
      with day fixed to the 15th (e.g., DJF->Jan 15).
    \'\'\'

    urls = {
        # UPDATED: CPC seasonal ONI (3-month means)
        "ONI": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
        # NEW: CPC seasonal RONI (3-month means)
        "RONI": "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",

        # Unchanged from prior function
        "PDO": "https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat",
        "PNA": "https://psl.noaa.gov/data/correlation/pna.data",
        "PMM-SST": "https://www.aos.wisc.edu/dvimont/MModes/RealTime/PMM.txt",
        "AMM-SST": "https://www.aos.wisc.edu/dvimont/MModes/RealTime/AMM.txt",
        "PMM-Wind": "https://www.aos.wisc.edu/dvimont/MModes/RealTime/PMM.txt",
        "AMM-Wind": "https://www.aos.wisc.edu/dvimont/MModes/RealTime/AMM.txt",
        "TNA": "https://psl.noaa.gov/data/correlation/tna.data",
        "AO": "https://psl.noaa.gov/data/correlation/ao.data",
        "NAO": "https://psl.noaa.gov/data/correlation/nao.data",
        "IOD": "https://sealevel.jpl.nasa.gov/api/v1/chartable_values/?category=254&per_page=-1&order=x+asc",
    }

    missing_values = {
        # CPC ONI/RONI: not typically present; keep for completeness
        "ONI": -99.9,
        "RONI": -99.9,

        "PDO": 99.99,
        "PNA": -99.90,
        "PMM-SST": None,
        "AMM-SST": None,
        "PMM-Wind": None,
        "AMM-Wind": None,
        "TNA": -99.99,
        "AO": -999.000,
        "NAO": -99.90,
    }

    if climate_index_name not in urls:
        raise ValueError(f"Unknown climate index: {climate_index_name}")

    url = urls[climate_index_name]
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    raw_data = resp.text

    # ---- Helper for CPC ONI/RONI seasonal format ----
    SEASON_TO_MIDMONTH = {
        "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
        "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
    }

    def _parse_cpc_oni_like(text: str, value_col: str = "value") -> pd.DataFrame:
        rows = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.upper().startswith("SEAS"):
                continue
            parts = re.split(r"\\s+", s)
            if len(parts) < 3:
                continue
            seas = parts[0].upper()
            if seas not in SEASON_TO_MIDMONTH:
                continue
            try:
                year = int(parts[1])
            except Exception:
                continue
            # CPC ONI has TOTAL and ANOM; RONI has ANOM; both have anomaly in last column
            try:
                val = float(parts[-1])
            except Exception:
                val = np.nan

            month = SEASON_TO_MIDMONTH[seas]
            time = pd.Timestamp(year=year, month=month, day=15)
            rows.append((time, val))

        df = pd.DataFrame(rows, columns=["time", value_col]).drop_duplicates("time", keep="last")
        df[value_col] = df[value_col].replace([-99.9, -99.90, -99.99, -999, -999.0, 99.99], np.nan)
        df = df.sort_values("time").reset_index(drop=True)
        return df

    # UPDATED/NEW: ONI + RONI from CPC
    if climate_index_name in ["ONI", "RONI"]:
        return _parse_cpc_oni_like(raw_data, value_col="value")

    # Legacy monthly/other formats below (unchanged behavior)
    if climate_index_name in ["PNA", "TNA", "AO", "NAO"]:
        lines = raw_data.splitlines()
        # PSL correlation format usually begins with two years on first line
        # and then year followed by 12 monthly values.
        data = []
        for line in lines[1:]:
            if line.strip() and line.split()[0].isdigit():
                tokens = line.split()
                year = int(tokens[0])
                vals = []
                for x in tokens[1:13]:
                    try:
                        fx = float(x)
                    except Exception:
                        fx = np.nan
                    if missing_values.get(climate_index_name) is not None and fx == missing_values[climate_index_name]:
                        fx = np.nan
                    vals.append(fx)
                if len(vals) == 12:
                    data.append([year] + vals)

        df = pd.DataFrame(data, columns=["Year"] + [f"Month_{i}" for i in range(1, 13)])
        df = df.melt(id_vars=["Year"], var_name="Month", value_name="value")
        df["Month"] = df["Month"].str.extract(r"(\\d+)").astype(int)
        df["time"] = pd.to_datetime(df[["Year", "Month"]].assign(Day=15))
        df.sort_values("time", inplace=True)
        return df[["time", "value"]].reset_index(drop=True)

    elif climate_index_name == "PDO":
        data = pd.read_csv(StringIO(raw_data), delim_whitespace=True, skiprows=1)
        data = data.melt(id_vars=["Year"], var_name="Month", value_name="value")
        months = {month: index for index, month in enumerate(
            [\'Jan\', \'Feb\', \'Mar\', \'Apr\', \'May\', \'Jun\',
             \'Jul\', \'Aug\', \'Sep\', \'Oct\', \'Nov\', \'Dec\'], start=1)}
        data["Month"] = data["Month"].map(months)
        data = data.dropna(subset=["Month"])
        data["Month"] = data["Month"].astype(int)
        data["time"] = pd.to_datetime(data[["Year", "Month"]].assign(Day=15))
        mv = missing_values.get("PDO", np.nan)
        data["value"] = data["value"].replace(mv, np.nan)
        data.sort_values("time", inplace=True)
        return data[["time", "value"]].reset_index(drop=True)

    elif climate_index_name == "IOD":
        iod_data = resp.json()
        if \'items\' not in iod_data:
            raise ValueError("Unexpected IOD data structure: \'items\' key not found.")

        def fractional_year_to_datetime(y: float) -> pd.Timestamp:
            year = int(np.floor(y))
            frac = y - year
            start = pd.Timestamp(year=year, month=1, day=1)
            end = pd.Timestamp(year=year+1, month=1, day=1)
            return start + (end - start) * frac

        items = iod_data[\'items\']
        df = pd.DataFrame({
            "time": [fractional_year_to_datetime(float(item[\'x\'])) for item in items],
            "value": [float(item[\'y\']) for item in items],
        }).set_index("time")

        monthly = df.resample(\'M\').mean()
        monthly.index = monthly.index + pd.Timedelta(days=15)
        monthly = monthly.reset_index()
        return monthly[["time", "value"]]

    elif climate_index_name in ["PMM-SST", "PMM-Wind", "AMM-SST", "AMM-Wind"]:
        columns = ["Year", "Month", "SST", "Wind"]
        data = pd.read_csv(StringIO(raw_data), delim_whitespace=True, names=columns, skiprows=1)
        data["time"] = pd.to_datetime(data[["Year", "Month"]].assign(Day=15))
        value_column = "SST" if "-SST" in climate_index_name else "Wind"
        data = data.rename(columns={value_column: "value"})
        data.sort_values("time", inplace=True)
        return data[["time", "value"]].reset_index(drop=True)

    raise ValueError(f"Unhandled climate index: {climate_index_name}")'''

registry.register(Tool(name="climate_tools", tags=frozenset({"climate"}), code=_code))
