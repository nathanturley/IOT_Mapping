"""
Build the interactive Leaflet map HTML file.

Combines a Folium base map with device markers, then injects the frontend
templates (CSS, HTML, JS) with encrypted data baked in. The result is a
single self-contained HTML file that handles auth and rendering client-side.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import folium
import pandas as pd

from iot_mapping.config import MARKER_STYLES, NZ_TZ, OFFLINE_COLOR
from iot_mapping.encryption import obfuscate_data

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def marker_style(dev_type: str, is_offline: bool = False) -> dict:
    """Pick a FontAwesome icon and colour based on device type. Offline devices turn red."""
    t = str(dev_type).lower()
    for key, style in MARKER_STYLES.items():
        if key != "default" and key in t:
            color = OFFLINE_COLOR if is_offline else style["color"]
            return {"icon": style["icon"], "color": color}
    fallback = MARKER_STYLES["default"]
    return {"icon": fallback["icon"], "color": OFFLINE_COLOR if is_offline else fallback["color"]}


def _get_display_name(device_row) -> str:
    """Use DeviceName if available, otherwise fall back to raw ID."""
    name = device_row.get("DeviceName")
    if isinstance(name, str) and name:
        return name
    return device_row["ID"]


def _build_tooltip(device_row) -> str:
    """Build the hover tooltip text shown on each map marker."""
    name = _get_display_name(device_row)
    loc = device_row.get("Location")
    has_location = isinstance(loc, str) and loc

    if has_location:
        return f"{name} — {loc}<br>ID: {device_row['ID']}"
    return f"{name}<br>ID: {device_row['ID']}"


def make_map(
    devices: pd.DataFrame,
    edges_with_coords: pd.DataFrame,
    out_html: str,
    aggregate: bool = True,
    min_count: int = 1,
    center_id: str = None,
    zoom_start: int = 9,
    offline_nodes: List[Tuple[str, str]] = None,
    password: str = None,
    scrape_timestamp: datetime = None,
) -> None:
    """Generate the complete interactive map HTML and write it to out_html."""

    # --- Centre the map on a specific device or the average of all devices ---
    if center_id and center_id.upper() in devices.index:
        ctr = [devices.loc[center_id.upper(), "Latitude"],
               devices.loc[center_id.upper(), "Longitude"]]
    else:
        ctr = [devices["Latitude"].mean(), devices["Longitude"].mean()]

    m = folium.Map(
        location=ctr,
        zoom_start=zoom_start,
        control_scale=True,
        prefer_canvas=True,
    )

    # --- Prepare edge data ---
    # Aggregate mode: group duplicate A->B edges and count them (most paths repeat).
    # Non-aggregate mode: draw every individual path as a separate line.
    if aggregate:
        agg = (
            edges_with_coords
            .groupby(["frm", "to", "lat_from", "lon_from", "lat_to", "lon_to"], as_index=False)
            .size()
        )
        agg = agg.rename(columns={"size": "count"})
        agg = agg[agg["count"] >= max(1, int(min_count))].copy()
    else:
        agg = edges_with_coords.copy()
        agg["count"] = 1

    edge_records = agg[["frm", "to", "lat_from", "lon_from", "lat_to", "lon_to", "count"]].to_dict(orient="records")

    # --- Prepare device data for the JS frontend ---
    for col in ["DeviceName", "Location"]:
        if col not in devices.columns:
            devices[col] = ""

    dev_df = devices.reset_index()[
        ["ID_upper", "ID", "Latitude", "Longitude", "Type", "DeviceName", "Location"]
    ].fillna("")
    device_records = dev_df.to_dict(orient="records")

    # Build a set of offline node IDs for quick lookup
    offline_node_ids = set()
    if offline_nodes:
        for _name, node_id in offline_nodes:
            offline_node_ids.add(node_id.upper().strip())

    # --- Encrypt data if a password was provided ---
    devices_json_plain = json.dumps(device_records)
    edges_json_plain = json.dumps(edge_records)

    if password:
        devices_json = obfuscate_data(devices_json_plain, password)
        edges_json = obfuscate_data(edges_json_plain, password)
        is_encrypted = "true"
    else:
        devices_json = devices_json_plain
        edges_json = edges_json_plain
        is_encrypted = "false"

    # --- Add a marker to the map for each device ---
    for id_upper, d in devices.iterrows():
        is_offline = id_upper in offline_node_ids
        style = marker_style(d.get("Type", ""), is_offline)

        marker = folium.Marker(
            location=[d["Latitude"], d["Longitude"]],
            tooltip=folium.Tooltip(_build_tooltip(d)),
            icon=folium.Icon(icon=style["icon"], color=style["color"], prefix="fa"),
        )
        marker.add_to(m)

    offline_nodes_json = json.dumps(offline_nodes if offline_nodes else [])
    offline_node_ids_json = json.dumps(list(offline_node_ids))

    # --- Resolve scrape timestamp to NZ time ---
    if scrape_timestamp is None:
        scrape_timestamp = datetime.now(NZ_TZ)
    elif scrape_timestamp.tzinfo is None:
        scrape_timestamp = scrape_timestamp.replace(tzinfo=NZ_TZ)
    else:
        scrape_timestamp = scrape_timestamp.astimezone(NZ_TZ)
    timestamp_iso = scrape_timestamp.isoformat()

    # --- Load the frontend templates and inject data via placeholder replacement ---
    # The templates use __PLACEHOLDER__ tokens that get swapped for real JSON here.
    # The result is a self-contained HTML file with everything embedded.
    css = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")
    html = (TEMPLATES_DIR / "map_shell.html").read_text(encoding="utf-8")
    js = (TEMPLATES_DIR / "map_app.js").read_text(encoding="utf-8")

    frontend = f"<style>{css}</style>\n{html}\n<script>{js}</script>"
    frontend = (
        frontend
        .replace("__DEVICES_JSON__", devices_json)
        .replace("__EDGES_JSON__", edges_json)
        .replace("__IS_ENCRYPTED__", is_encrypted)
        .replace("__OFFLINE_NODES_JSON__", offline_nodes_json)
        .replace("__OFFLINE_NODE_IDS_JSON__", offline_node_ids_json)
        .replace("__SCRAPE_TIMESTAMP__", timestamp_iso)
    )

    m.get_root().html.add_child(folium.Element(frontend))
    m.save(out_html)
    logger.info("Wrote %s", out_html)
