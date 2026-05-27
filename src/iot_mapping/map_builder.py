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
    t = str(dev_type).lower()
    for key, style in MARKER_STYLES.items():
        if key != "default" and key in t:
            color = OFFLINE_COLOR if is_offline else style["color"]
            return {"icon": style["icon"], "color": color}
    fallback = MARKER_STYLES["default"]
    return {"icon": fallback["icon"], "color": OFFLINE_COLOR if is_offline else fallback["color"]}


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

    # Aggregate or pass-through edges
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

    # Ensure DeviceName/Location columns exist
    for col in ["DeviceName", "Location"]:
        if col not in devices.columns:
            devices[col] = ""

    dev_df = devices.reset_index()[
        ["ID_upper", "ID", "Latitude", "Longitude", "Type", "DeviceName", "Location"]
    ].fillna("")
    device_records = dev_df.to_dict(orient="records")

    offline_node_ids = set()
    if offline_nodes:
        for _name, node_id in offline_nodes:
            offline_node_ids.add(node_id.upper().strip())

    # Serialise and optionally encrypt data
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

    # Add device markers
    for id_upper, d in devices.iterrows():
        is_offline = id_upper in offline_node_ids
        style = marker_style(d.get("Type", ""), is_offline)

        name = d.get("DeviceName") if isinstance(d.get("DeviceName"), str) and d.get("DeviceName") else d["ID"]
        loc = d.get("Location") if isinstance(d.get("Location"), str) and d.get("Location") else None

        if loc:
            tip = f"{name} — {loc}<br>ID: {d['ID']}"
        else:
            tip = f"{name}<br>ID: {d['ID']}"

        marker = folium.Marker(
            location=[d["Latitude"], d["Longitude"]],
            tooltip=folium.Tooltip(tip),
            icon=folium.Icon(icon=style["icon"], color=style["color"], prefix="fa"),
        )
        marker.add_to(m)

    offline_nodes_json = json.dumps(offline_nodes if offline_nodes else [])
    offline_node_ids_json = json.dumps(list(offline_node_ids))

    # Resolve scrape timestamp
    if scrape_timestamp is None:
        scrape_timestamp = datetime.now(NZ_TZ)
    elif scrape_timestamp.tzinfo is None:
        scrape_timestamp = scrape_timestamp.replace(tzinfo=NZ_TZ)
    else:
        scrape_timestamp = scrape_timestamp.astimezone(NZ_TZ)
    timestamp_iso = scrape_timestamp.isoformat()

    # Load frontend templates and inject data
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
