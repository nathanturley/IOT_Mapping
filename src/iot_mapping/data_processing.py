import pandas as pd


def build_edges(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in df.iterrows():
        seq = [row.get(k) for k in ["node_U", "hop1_U", "hop2_U", "hop3_U", "hop4_U", "hop5_U", "hop6_U"]]
        seq = [s for s in seq if s and s != ""]
        if len(seq) < 2:
            continue
        for i in range(len(seq) - 1):
            records.append({
                "timestamp": row.get("timestamp"),
                "frm": seq[i],
                "to": seq[i + 1],
                "order": i,
                "count_row": row.get("count"),
            })
    return pd.DataFrame.from_records(records)


def add_coords(edges: pd.DataFrame, devices: pd.DataFrame) -> pd.DataFrame:
    merged = edges.merge(
        devices[["Latitude", "Longitude"]],
        left_on="frm", right_index=True, how="left",
    ).rename(columns={"Latitude": "lat_from", "Longitude": "lon_from"})

    merged = merged.merge(
        devices[["Latitude", "Longitude"]],
        left_on="to", right_index=True, how="left",
    ).rename(columns={"Latitude": "lat_to", "Longitude": "lon_to"})

    merged = merged.dropna(subset=["lat_from", "lon_from", "lat_to", "lon_to"])
    return merged
