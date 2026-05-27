import os
import re

import pandas as pd


def find_column(df: pd.DataFrame, name: str) -> str | None:
    """Find a DataFrame column by case-insensitive name match."""
    for c in df.columns:
        if c.strip().lower() == name:
            return c
    return None


def load_devices(dev_path: str) -> pd.DataFrame:
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
    out["ID_upper"] = out["ID"].str.upper().str.strip()
    out = out.set_index("ID_upper", drop=True)
    return out


def load_labels(labels_path: str) -> pd.DataFrame:
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
    """Extract GMT offset from a timestamp string and return (cleaned_time, offset_hours)."""
    if not isinstance(timestr, str):
        return str(timestr), 0
    m = re.search(r"GMT([+-]\d{1,2})", timestr)
    offset = int(m.group(1)) if m else 0
    cleaned = re.sub(r"\s*GMT[+-]\d{1,2}\s*", "", timestr).strip()
    return cleaned, offset


def load_paths(paths_path: str, sample: int = None, sep_mode: str = "auto") -> pd.DataFrame:
    if sep_mode == "comma":
        sep = r","
    elif sep_mode == "tab":
        sep = r"\t+"
    else:
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

    times = df["time"].apply(parse_time_and_offset)
    df["time_clean"] = times.apply(lambda t: t[0])
    df["gmt_offset_h"] = times.apply(lambda t: t[1])
    df["timestamp"] = pd.to_datetime(
        df["date"].str.strip() + " " + df["time_clean"],
        dayfirst=True,
        errors="coerce",
    )

    id_cols = ["node", "hop1", "hop2", "hop3", "hop4", "hop5", "hop6"]
    for c in id_cols:
        df[c] = df[c].replace({"nan": None})
        df[c] = df[c].apply(lambda x: x if (x and x != "None") else None)
        df[c + "_U"] = df[c].apply(lambda s: s.upper().strip() if isinstance(s, str) else None)

    return df
