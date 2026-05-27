"""
Load and normalise the three input files:
  - devices  (coordinates + type for each node)
  - labels   (friendly names and locations)
  - paths    (radio hop sequences from the path log)
"""

import os
import re

import pandas as pd


def find_column(df: pd.DataFrame, name: str) -> str | None:
    """
    Find a DataFrame column by case-insensitive match.
    Needed because input CSVs are inconsistent with capitalisation.
    """
    for c in df.columns:
        if c.strip().lower() == name:
            return c
    return None


def load_devices(dev_path: str) -> pd.DataFrame:
    """
    Load device coordinates from CSV or Excel.
    Returns a DataFrame indexed by ID_upper (uppercase ID) with columns:
    ID, Latitude, Longitude, Type.
    """
    ext = os.path.splitext(dev_path)[1].lower()
    if ext == ".xlsx":
        df = pd.read_excel(dev_path)
    else:
        df = pd.read_csv(dev_path)

    id_col = find_column(df, "id")
    lat_col = find_column(df, "latitude")
    lon_col = find_column(df, "longitude")
    type_col = find_column(df, "type")

    if not all([id_col, lat_col, lon_col]):
        raise ValueError("Devices file must include columns: ID, Latitude, Longitude")

    out = pd.DataFrame({
        "ID": df[id_col].astype(str).str.strip(),
        "Latitude": pd.to_numeric(df[lat_col], errors="coerce"),
        "Longitude": pd.to_numeric(df[lon_col], errors="coerce"),
    })
    out["Type"] = df[type_col].astype(str).str.strip() if type_col else ""

    out = out.dropna(subset=["Latitude", "Longitude"])

    # Uppercase index so joins against path data are case-insensitive
    out["ID_upper"] = out["ID"].str.upper().str.strip()
    out = out.set_index("ID_upper", drop=True)
    return out


def load_labels(labels_path: str) -> pd.DataFrame:
    """Load friendly device names and locations. Indexed by ID_upper."""
    df = pd.read_csv(labels_path)

    id_col = find_column(df, "id")
    name_col = find_column(df, "devicename")
    loc_col = find_column(df, "location")
    if not all([id_col, name_col, loc_col]):
        raise ValueError("Labels file must include columns: ID, DeviceName, Location")

    out = pd.DataFrame({
        "ID": df[id_col].astype(str).str.strip(),
        "DeviceName": df[name_col].astype(str).str.strip(),
        "Location": df[loc_col].astype(str).str.strip(),
    })
    out["ID_upper"] = out["ID"].str.upper().str.strip()
    out = out.set_index("ID_upper", drop=True)
    return out


def parse_time_and_offset(timestr: str) -> tuple[str, int]:
    """
    Parse strings like '14:32:15 GMT+12' into ('14:32:15', 12).
    Returns (cleaned_time, offset_hours). Falls back to 0 offset if no GMT found.
    """
    if not isinstance(timestr, str):
        return str(timestr), 0
    m = re.search(r"GMT([+-]\d{1,2})", timestr)
    offset = int(m.group(1)) if m else 0
    cleaned = re.sub(r"\s*GMT[+-]\d{1,2}\s*", "", timestr).strip()
    return cleaned, offset


def _clean_hop_value(val: str) -> str | None:
    """Turn empty strings, 'nan', and 'None' into actual None."""
    if not val or val in ("nan", "None"):
        return None
    return val


def load_paths(paths_path: str, sample: int = None, sep_mode: str = "auto") -> pd.DataFrame:
    """
    Load the radio path log file.

    Each row is one observed path: a source node followed by up to 6 hops
    (repeaters/gateways) that the signal passed through.

    Returns a DataFrame with columns for each hop plus uppercase variants
    (node_U, hop1_U, ...) used for case-insensitive joins.
    """
    if sep_mode == "comma":
        sep = r","
    elif sep_mode == "tab":
        sep = r"\t+"
    else:
        # Auto-detect: accept either tabs or commas
        sep = r"[\t,]+"

    df = pd.read_csv(
        paths_path,
        sep=sep,
        engine="python",
        header=None,
        names=["count", "date", "time", "node", "hop1", "hop2", "hop3", "hop4", "hop5", "hop6"],
        dtype=str,
    )
    if sample:
        df = df.iloc[:sample].copy()

    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    # Split '14:32:15 GMT+12' into clean time and offset
    times = df["time"].apply(parse_time_and_offset)
    df["time_clean"] = times.apply(lambda t: t[0])
    df["gmt_offset_h"] = times.apply(lambda t: t[1])
    df["timestamp"] = pd.to_datetime(
        df["date"].str.strip() + " " + df["time_clean"],
        dayfirst=True,
        errors="coerce",
    )

    # Clean hop columns and create uppercase versions for case-insensitive joins
    hop_cols = ["node", "hop1", "hop2", "hop3", "hop4", "hop5", "hop6"]
    for c in hop_cols:
        df[c] = df[c].apply(_clean_hop_value)
        df[c + "_U"] = df[c].apply(lambda s: s.upper().strip() if isinstance(s, str) else None)

    return df
