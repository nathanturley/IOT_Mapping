"""
Transform raw path data into network edges with coordinates.

Data flow:
  path log rows  -->  build_edges()  -->  pairwise edges  -->  add_coords()  -->  edges with lat/lon
"""

import pandas as pd


def build_edges(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert hop sequences into pairwise directed edges.

    A path like [A, B, C] becomes two edges: A->B and B->C.
    Uses the uppercase hop columns (node_U, hop1_U, ...) so IDs match
    regardless of how they were capitalised in the source data.
    """
    records = []
    for _, row in df.iterrows():
        # Collect the full hop sequence for this path, skipping empty hops
        seq = [row.get(k) for k in ["node_U", "hop1_U", "hop2_U", "hop3_U", "hop4_U", "hop5_U", "hop6_U"]]
        seq = [s for s in seq if s and s != ""]

        # Need at least 2 nodes to form an edge
        if len(seq) < 2:
            continue

        # Create an edge for each consecutive pair in the sequence
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
    """
    Join lat/lon coordinates onto both endpoints of each edge.

    Merges the devices table twice — once for the 'from' node and once for the
    'to' node. Edges where either endpoint is missing from the devices table
    are dropped (they'd have no position on the map).
    """
    # Get coordinates for the 'from' end of each edge
    merged = edges.merge(
        devices[["Latitude", "Longitude"]],
        left_on="frm", right_index=True, how="left",
    ).rename(columns={"Latitude": "lat_from", "Longitude": "lon_from"})

    # Get coordinates for the 'to' end of each edge
    merged = merged.merge(
        devices[["Latitude", "Longitude"]],
        left_on="to", right_index=True, how="left",
    ).rename(columns={"Latitude": "lat_to", "Longitude": "lon_to"})

    # Drop edges where we couldn't find coordinates for both endpoints
    merged = merged.dropna(subset=["lat_from", "lon_from", "lat_to", "lon_to"])
    return merged
