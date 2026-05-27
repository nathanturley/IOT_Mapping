import argparse
import logging
import os
from datetime import datetime

import pandas as pd

from iot_mapping.config import (
    CI_SCRAPER_WAIT,
    DEFAULT_ZOOM,
    LOCAL_SCRAPER_WAIT,
    NZ_TZ,
    THINGSBOARD_DASHBOARD_URL,
)
from iot_mapping.data_loader import load_devices, load_labels, load_paths
from iot_mapping.data_processing import add_coords, build_edges
from iot_mapping.map_builder import make_map
from iot_mapping.scraper import get_offline_nodes

logger = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an interactive IoT sensor network map.")
    ap.add_argument("--paths", required=True, help="Path to paths CSV/TSV file.")
    ap.add_argument("--devices", required=True, help="Path to devices file (.xlsx or .csv).")
    ap.add_argument("--labels", help="Path to labels CSV (ID, DeviceName, Location).")
    ap.add_argument("--sep", choices=["auto", "comma", "tab"], default="auto", help="Separator mode for paths file.")
    ap.add_argument("--out", default="routes_map.html", help="Output HTML map file.")
    ap.add_argument("--sample", type=int, default=None, help="Use only first N rows of path log.")
    ap.add_argument("--aggregate", dest="aggregate", action="store_true", help="Aggregate edges and weight by count.")
    ap.add_argument("--no-aggregate", dest="aggregate", action="store_false", help="Draw every individual path.")
    ap.add_argument("--min-count", type=int, default=1, help="Minimum edge count threshold (aggregate mode).")
    ap.add_argument("--center", dest="center_id", default=None, help="Device ID to center the map on.")
    ap.add_argument("--zoom", dest="zoom_start", type=int, default=DEFAULT_ZOOM, help="Initial zoom level.")
    ap.add_argument("--skip-offline", dest="skip_offline", action="store_true", help="Skip fetching offline nodes.")
    ap.add_argument("--password", default=None, help="Password for data obfuscation.")
    ap.set_defaults(aggregate=True, skip_offline=False)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    devices = load_devices(args.devices)

    if args.labels:
        labels = load_labels(args.labels)
        devices = devices.join(labels[["DeviceName", "Location"]], how="left")

    paths = load_paths(args.paths, sample=args.sample, sep_mode=args.sep)
    edges = build_edges(paths)
    edges_xy = add_coords(edges, devices)

    # Diagnostics for missing coordinates
    total_edges = len(edges)
    edges_with_xy = len(edges_xy)
    missing = total_edges - edges_with_xy
    if missing > 0:
        involved_ids = set(edges["frm"]).union(set(edges["to"]))
        known_ids = set(devices.index)
        missing_ids = sorted(str(i) for i in involved_ids if pd.notna(i) and i not in known_ids)
        logger.warning("%d edges dropped due to missing coordinates.", missing)
        if len(missing_ids) <= 50:
            logger.warning("Missing device IDs: %s", ", ".join(missing_ids))
        else:
            logger.warning("%d device IDs lack coordinates (not listed).", len(missing_ids))

    # Fetch offline nodes from ThingsBoard
    offline_nodes = None
    if not args.skip_offline:
        try:
            logger.info("Fetching offline nodes from ThingsBoard...")
            wait_time = CI_SCRAPER_WAIT if os.environ.get("CI") else LOCAL_SCRAPER_WAIT
            offline_nodes = get_offline_nodes(
                THINGSBOARD_DASHBOARD_URL,
                wait_time=wait_time,
                headless=True,
            )
            if offline_nodes:
                logger.info("Found %d offline nodes", len(offline_nodes))
            else:
                logger.info("No offline nodes found")
        except Exception:
            logger.exception("Failed to fetch offline nodes")
            offline_nodes = None

    make_map(
        devices,
        edges_xy,
        args.out,
        aggregate=args.aggregate,
        min_count=args.min_count,
        center_id=args.center_id,
        zoom_start=args.zoom_start,
        offline_nodes=offline_nodes,
        password=args.password,
        scrape_timestamp=datetime.now(NZ_TZ),
    )


if __name__ == "__main__":
    main()
