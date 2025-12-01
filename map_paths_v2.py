#!/usr/bin/env python3
"""
Map radio paths (sensor -> repeaters -> gateway) onto an interactive map,
with optional labels file for friendly names and locations.

Inputs
------
1) Path log file (CSV or TSV) where each line is:
   count, date, time_with_GMT, node, hop1, hop2, hop3, hop4, hop5, hop6
   (if TSV, use tabs; mixed separators can be handled with --sep auto)

2) Device coordinates file: Excel (.xlsx) or CSV (.csv) with columns:
   ID, Latitude, Longitude[, Type]
   - ID must match the node/repeater/gateway IDs in the log (case-insensitive match is handled).
   - Type is optional (e.g. Sensor/Repeater/Gateway) — used ONLY for marker colour/icon if present.
   - Tooltip no longer shows Type.

3) Labels file (optional): CSV with columns:
   ID, DeviceName, Location
   - Used to enhance tooltips. On hover we show: DeviceName, Location, and ID.

Usage
-----
python map_paths_v2.py --paths paths.csv --devices devices.csv --labels labels.csv --out routes_map.html

Common flags
-----------
--sep auto|comma|tab  : how to parse the paths file (default: auto)
--sample N            : use only the first N rows from the path log
--aggregate / --no-aggregate
--min-count K
--show-markers / --hide-markers
--center ID
--zoom Z
"""

import argparse
import math
import os
import re
from typing import List, Tuple
import json
import base64

import pandas as pd
import folium
import thingsboard_scraper


def obfuscate_data(data_string: str, password: str) -> str:
    """
    XOR-encrypt data with password and base64 encode.
    
    How it works:
    1. Convert password and data to bytes
    2. For each byte in data, XOR with corresponding password byte
    3. Password cycles if data is longer than password
    4. Base64 encode result so it's safe to embed in HTML/JS
    
    Args:
        data_string: JSON string to encrypt
        password: Password to use as encryption key
    
    Returns:
        Base64-encoded encrypted string
    """
    if not password:
        return data_string  # No password = no encryption (dev mode)
    
    # Convert password to bytes
    key_bytes = password.encode('utf-8')
    data_bytes = data_string.encode('utf-8')
    
    # XOR each byte with password bytes (cycling through password)
    obfuscated = bytearray()
    for i, byte in enumerate(data_bytes):
        # i % len(key_bytes) cycles through password if data is longer
        obfuscated.append(byte ^ key_bytes[i % len(key_bytes)])
    
    # Base64 encode so we can safely put it in HTML/JavaScript
    return base64.b64encode(obfuscated).decode('utf-8')


def load_devices(dev_path: str) -> pd.DataFrame:
    ext = os.path.splitext(dev_path)[1].lower()
    if ext == ".xlsx":
        df = pd.read_excel(dev_path)
    else:
        # default assume CSV
        df = pd.read_csv(dev_path)
    # Normalise column names (case-insensitive)
    def col(df, name):  # pick column by case-insensitive match
        for c in df.columns:
            if c.strip().lower() == name:
                return c
        return None

    id_col = col(df, "id")
    lat_col = col(df, "latitude")
    lon_col = col(df, "longitude")
    type_col = col(df, "type")

    if not all([id_col, lat_col, lon_col]):
        raise ValueError("Devices file must include columns: ID, Latitude, Longitude")

    out = pd.DataFrame({
        "ID": df[id_col].astype(str).str.strip(),
        "Latitude": pd.to_numeric(df[lat_col], errors="coerce"),
        "Longitude": pd.to_numeric(df[lon_col], errors="coerce"),
    })
    out["Type"] = df[type_col].astype(str).str.strip() if type_col else ""

    # Drop rows with missing coordinates
    out = out.dropna(subset=["Latitude", "Longitude"])
    # Uppercase index for tolerant lookup
    out["ID_upper"] = out["ID"].str.upper().str.strip()
    out = out.set_index("ID_upper", drop=True)
    return out


def load_labels(labels_path: str) -> pd.DataFrame:
    df = pd.read_csv(labels_path)
    # Case-insensitive column picking
    def col(df, name):
        for c in df.columns:
            if c.strip().lower() == name:
                return c
        return None

    id_col = col(df, "id")
    name_col = col(df, "devicename")
    loc_col = col(df, "location")
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


def parse_time_and_offset(timestr: str):
    """
    Extract GMT offset like 'GMT+12' to integer hours and return cleaned time string (without GMT part).
    """
    if not isinstance(timestr, str):
        return str(timestr), 0
    m = re.search(r"GMT([+-]\d{1,2})", timestr)
    offset = int(m.group(1)) if m else 0
    cleaned = re.sub(r"\s*GMT[+-]\d{1,2}\s*", "", timestr).strip()
    return cleaned, offset


def load_paths(paths_path: str, sample: int = None, sep_mode: str = "auto") -> pd.DataFrame:
    # Choose separator
    if sep_mode == "comma":
        sep = r","
    elif sep_mode == "tab":
        sep = r"\t+"
    else:
        # auto-detect: allow tabs or commas
        sep = r"[\t,]+"

    df = pd.read_csv(
        paths_path,
        sep=sep,
        engine="python",
        header=None,
        names=["count", "date", "time", "node", "hop1", "hop2", "hop3", "hop4", "hop5", "hop6"],
        dtype=str
    )
    if sample:
        df = df.iloc[:sample].copy()

    # Normalise strings
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    # Parse time & GMT offset
    times = df["time"].apply(parse_time_and_offset)
    df["time_clean"] = times.apply(lambda t: t[0])
    df["gmt_offset_h"] = times.apply(lambda t: t[1])
    df["timestamp"] = pd.to_datetime(df["date"].str.strip() + " " + df["time_clean"], dayfirst=True, errors="coerce")

    # Uppercase IDs for robust joins
    id_cols = ["node", "hop1", "hop2", "hop3", "hop4", "hop5", "hop6"]
    for c in id_cols:
        df[c] = df[c].replace({"nan": None})
        df[c] = df[c].apply(lambda x: x if (x and x != "None") else None)
        df[c + "_U"] = df[c].apply(lambda s: s.upper().strip() if isinstance(s, str) else None)

    return df


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
        left_on="frm", right_index=True, how="left"
    ).rename(columns={"Latitude": "lat_from", "Longitude": "lon_from"})

    merged = merged.merge(
        devices[["Latitude", "Longitude"]],
        left_on="to", right_index=True, how="left"
    ).rename(columns={"Latitude": "lat_to", "Longitude": "lon_to"})

    merged = merged.dropna(subset=["lat_from", "lon_from", "lat_to", "lon_to"])
    return merged


def make_map(devices: pd.DataFrame,
             edges_with_coords: pd.DataFrame,
             out_html: str,
             aggregate: bool = True,
             min_count: int = 1,
             show_markers: bool = True,  # kept but we always show markers in JS
             center_id: str = None,
             zoom_start: int = 9,
             offline_nodes: List[Tuple[str, str]] = None,
             password: str = None):

    # Determine map centre
    if center_id and center_id.upper() in devices.index:
        ctr = [devices.loc[center_id.upper(), "Latitude"],
               devices.loc[center_id.upper(), "Longitude"]]
    else:
        ctr = [devices["Latitude"].mean(),
               devices["Longitude"].mean()]

    # Base Leaflet map via Folium
    m = folium.Map(location=ctr,
                   zoom_start=zoom_start,
                   control_scale=True,
                   prefer_canvas=True)

    # ---------- Prepare edge data (aggregate or per-edge) ----------
    if aggregate:
        agg = (edges_with_coords
               .groupby(["frm", "to",
                         "lat_from", "lon_from",
                         "lat_to", "lon_to"], as_index=False)
               .size())
        agg = agg.rename(columns={"size": "count"})
        agg = agg[agg["count"] >= max(1, int(min_count))].copy()
    else:
        agg = edges_with_coords.copy()
        agg["count"] = 1

    edge_records_df = agg[["frm", "to",
                           "lat_from", "lon_from",
                           "lat_to", "lon_to",
                           "count"]].copy()
    edge_records = edge_records_df.to_dict(orient="records")

    # ---------- Prepare device data for JS ----------
    # Ensure DeviceName/Location exist (even if labels file not provided)
    for col in ["DeviceName", "Location"]:
        if col not in devices.columns:
            devices[col] = ""

    dev_df = devices.reset_index()[["ID_upper", "ID",
                                    "Latitude", "Longitude",
                                    "Type", "DeviceName",
                                    "Location"]].copy()
    dev_df = dev_df.fillna("")
    device_records = dev_df.to_dict(orient="records")

    # Create set of offline node IDs (uppercase) for quick lookup
    offline_node_ids = set()
    if offline_nodes:
        for name, node_id in offline_nodes:
            offline_node_ids.add(node_id.upper().strip())

    # Prepare JSON data
    devices_json_plain = json.dumps(device_records)
    edges_json_plain = json.dumps(edge_records)

    # Obfuscate if password provided
    if password:
        devices_json = obfuscate_data(devices_json_plain, password)
        edges_json = obfuscate_data(edges_json_plain, password)
        is_encrypted = "true"
    else:
        devices_json = devices_json_plain
        edges_json = edges_json_plain
        is_encrypted = "false"

    # ---------- Add icon markers to map ----------
    def marker_style(dev_type: str, is_offline: bool = False):
        t = str(dev_type).lower()
        if "gate" in t:
            return dict(icon="cloud", color="red" if is_offline else "purple")      # Gateway: purple/red
        if "rep" in t:
            return dict(icon="exchange", color="red" if is_offline else "pink")         # Repeater: pink/red
        if "tank" in t:
            return dict(icon="tint", color="red" if is_offline else "blue")          # Tank: blue/red
        if "stream" in t:
            return dict(icon="tint", color="red" if is_offline else "green")          # Stream sensor: green/red
        return dict(icon="circle", color="red" if is_offline else "gray")

    for id_upper, d in devices.iterrows():
        is_offline = id_upper in offline_node_ids
        style = marker_style(d.get("Type", ""), is_offline)
        # Tooltip text: DeviceName, Location, ID
        name = d.get("DeviceName") if isinstance(d.get("DeviceName"), str) and d.get("DeviceName") else d["ID"]
        loc = d.get("Location") if isinstance(d.get("Location"), str) and d.get("Location") else None

        if loc:
            tip = f"{name} — {loc}<br>ID: {d['ID']}"
        else:
            tip = f"{name}<br>ID: {d['ID']}"

        # Create marker with custom properties for device ID
        marker = folium.Marker(
            location=[d["Latitude"], d["Longitude"]],
            tooltip=folium.Tooltip(tip),
            icon=folium.Icon(icon=style["icon"], color=style["color"], prefix="fa")
        )
        marker.add_to(m)
    
    # Prepare offline nodes data
    offline_nodes_json = json.dumps(offline_nodes if offline_nodes else [])
    offline_node_ids_json = json.dumps(list(offline_node_ids))
    
    map_name = m.get_name()

    # ---------- Inject search UI + JS ----------
    search_html = """
<style>
  #loginModal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.95);
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  #loginBox {
    background: white;
    padding: 40px;
    border-radius: 12px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
    max-width: 400px;
    width: 90%;
  }
  #loginBox h2 {
    margin: 0 0 10px 0;
    color: #333;
    font-size: 24px;
  }
  #loginBox p {
    margin: 0 0 20px 0;
    color: #666;
    font-size: 14px;
  }
  #loginBox input[type="password"] {
    width: 100%;
    padding: 12px;
    border: 2px solid #ddd;
    border-radius: 6px;
    font-size: 16px;
    box-sizing: border-box;
    margin-bottom: 10px;
  }
  #loginBox input[type="password"]:focus {
    outline: none;
    border-color: #4CAF50;
  }
  #loginBox button {
    width: 100%;
    padding: 12px;
    background: #4CAF50;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    cursor: pointer;
    font-weight: 600;
  }
  #loginBox button:hover {
    background: #45a049;
  }
  #loginBox .remember-me {
    margin: 15px 0;
    display: flex;
    align-items: center;
    font-size: 14px;
    color: #666;
  }
  #loginBox .remember-me input {
    margin-right: 8px;
  }
  #loginError {
    color: #d32f2f;
    font-size: 14px;
    margin-top: 10px;
    display: none;
  }
  #logoutBtn {
    position: absolute;
    top: 10px;
    left: 280px;
    z-index: 1000;
    background: #f44336;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
  }
  #logoutBtn:hover {
    background: #d32f2f;
  }
  #searchContainer {
    position: absolute;
    top: 10px;
    right: 10px;
    z-index: 1000;
    background: white;
    padding: 8px;
    border-radius: 4px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    max-height: 260px;
    width: 260px;
    overflow: hidden;
    font-size: 12px;
  }
  #nodeSearch {
    width: 100%;
    box-sizing: border-box;
    padding: 4px 6px;
    margin-bottom: 4px;
    border: 1px solid #ccc;
    border-radius: 3px;
  }
  #searchResults {
    max-height: 210px;
    overflow-y: auto;
  }
  .search-result {
    padding: 3px 4px;
    cursor: pointer;
    border-radius: 3px;
    border-bottom: 1px solid #eee;
  }
  .search-result:hover {
    background: #f0f0f0;
  }
  #offlineContainer {
    position: absolute;
    bottom: 30px;
    left: 10px;
    z-index: 1000;
    background: white;
    padding: 10px;
    border-radius: 4px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    max-height: 300px;
    width: 280px;
    overflow: hidden;
    font-size: 12px;
  }
  #offlineContainer h4 {
    margin: 0 0 8px 0;
    font-size: 13px;
    font-weight: bold;
    color: #d32f2f;
  }
  #offlineList {
    max-height: 300px;
    overflow-y: auto;
  }
  .offline-item {
    padding: 6px 8px;
    cursor: pointer;
    border-radius: 3px;
    border-bottom: 1px solid #eee;
    margin-bottom: 2px;
  }
  .offline-item:hover {
    background: #ffebee;
  }
  .offline-name {
    font-weight: 500;
    color: #333;
  }
  .offline-id {
    font-size: 11px;
    color: #666;
    margin-top: 2px;
  }
  #legend {
    position: absolute;
    bottom: 30px;
    right: 10px;
    z-index: 1000;
    background: white;
    padding: 10px;
    border-radius: 4px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    font-size: 12px;
    line-height: 1.6;
  }
  #legend h4 {
    margin: 0 0 8px 0;
    font-size: 13px;
    font-weight: bold;
  }
  .legend-item {
    display: flex;
    align-items: center;
    margin-bottom: 4px;
  }
  .legend-icon {
    width: 20px;
    height: 20px;
    margin-right: 8px;
    border-radius: 2px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: white;
  }
  .legend-icon.purple { background-color: #cf51b6; }
  .legend-icon.pink { background-color: #ff91e8; }
  .legend-icon.blue { background-color: #38a9dc;  }
  .legend-icon.green { background-color: #71af26; }
</style>

<div id="loginModal" style="display: none;">
  <div id="loginBox">
    <h2>Map Authentication</h2>
    <p>Please enter the password to view this map.</p>
    <input type="password" id="mapPassword" placeholder="Enter password" autocomplete="off" />
    <div class="remember-me">
      <input type="checkbox" id="rememberMe" />
      <label for="rememberMe">Remember me on this device</label>
    </div>
    <button onclick="attemptLogin()">Login</button>
    <div id="loginError">Incorrect password. Please try again.</div>
  </div>
</div>

<button id="logoutBtn" style="display: none;" onclick="logout()">Logout</button>

<div id="searchContainer">
  <input id="nodeSearch" type="text"
         placeholder="Search by ID, name, location" />
  <div id="searchResults"></div>
</div>

<div id="offlineContainer">
  <h4>Offline Nodes</h4>
  <div id="offlineList"></div>
</div>

<div id="legend">
  <h4>Legend</h4>
  <div class="legend-item">
    <div class="legend-icon purple"><i class="fa fa-cloud"></i></div>
    <span>Gateways</span>
  </div>
  <div class="legend-item">
    <div class="legend-icon pink"><i class="fa fa-exchange"></i></div>
    <span>Repeaters</span>
  </div>
  <div class="legend-item">
    <div class="legend-icon blue"><i class="fa fa-tint"></i></div>
    <span>Water Tanks</span>
  </div>
  <div class="legend-item">
    <div class="legend-icon green"><i class="fa fa-tint"></i></div>
    <span>Stream Sensors</span>
  </div>
</div>

<script>
  // Configuration from Python
  var encryptedDevices = "__DEVICES_JSON__";
  var encryptedEdges = "__EDGES_JSON__";
  var isEncrypted = __IS_ENCRYPTED__;
  var offlineNodes = __OFFLINE_NODES_JSON__;
  var offlineNodeIds = __OFFLINE_NODE_IDS_JSON__;
  var mapObj = __MAP_NAME__;

  // Global variables for decrypted data
  var devices = null;
  var edges = null;

  // XOR decryption function (reverse of Python obfuscation)
  function deobfuscate(base64Data, password) {
    try {
      // Decode base64
      let encrypted = atob(base64Data);
      
      // Convert password to bytes
      let encoder = new TextEncoder();
      let keyBytes = encoder.encode(password);
      
      // XOR decrypt
      let decrypted = '';
      for (let i = 0; i < encrypted.length; i++) {
        // XOR with cycling password bytes
        let decryptedByte = encrypted.charCodeAt(i) ^ keyBytes[i % keyBytes.length];
        decrypted += String.fromCharCode(decryptedByte);
      }
      
      return decrypted;
    } catch (e) {
      throw new Error('Decryption failed');
    }
  }

  // Attempt login with password
  function attemptLogin() {
    let password = document.getElementById('mapPassword').value;
    let remember = document.getElementById('rememberMe').checked;
    let errorDiv = document.getElementById('loginError');
    
    if (!password) {
      errorDiv.textContent = 'Please enter a password';
      errorDiv.style.display = 'block';
      return;
    }
    
    try {
      // Try to decrypt data
      let devicesJson = deobfuscate(encryptedDevices, password);
      let edgesJson = deobfuscate(encryptedEdges, password);
      
      // Try to parse as JSON (validates password is correct)
      devices = JSON.parse(devicesJson);
      edges = JSON.parse(edgesJson);
      
      // Success! Store auth token
      let authToken = btoa(password);
      let storage = remember ? localStorage : sessionStorage;
      storage.setItem('mapAuth', authToken);
      
      // Hide login modal
      document.getElementById('loginModal').style.display = 'none';
      
      // Show logout button
      document.getElementById('logoutBtn').style.display = 'block';
      
      // Initialize map with decrypted data
      initializeMap();
      
    } catch (e) {
      // Decryption or parsing failed = wrong password
      errorDiv.textContent = 'Incorrect password. Please try again.';
      errorDiv.style.display = 'block';
      document.getElementById('mapPassword').value = '';
      document.getElementById('mapPassword').focus();
    }
  }

  // Logout function
  function logout() {
    localStorage.removeItem('mapAuth');
    sessionStorage.removeItem('mapAuth');
    location.reload();
  }

  // Allow Enter key to submit
  document.addEventListener('DOMContentLoaded', function() {
    let passwordInput = document.getElementById('mapPassword');
    if (passwordInput) {
      passwordInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
          attemptLogin();
        }
      });
    }
  });

  // Check for existing session on page load
  function checkAuth() {
    console.log('=== checkAuth called ===');
    console.log('isEncrypted:', isEncrypted);
    console.log('Modal element:', document.getElementById('loginModal'));
    
    let storedAuth = localStorage.getItem('mapAuth') || sessionStorage.getItem('mapAuth');
    console.log('storedAuth:', storedAuth);
    
    if (storedAuth && isEncrypted) {
      // Try to auto-login with stored password
      console.log('Attempting auto-login...');
      try {
        let password = atob(storedAuth);
        let devicesJson = deobfuscate(encryptedDevices, password);
        let edgesJson = deobfuscate(encryptedEdges, password);
        
        devices = JSON.parse(devicesJson);
        edges = JSON.parse(edgesJson);
        
        // Success! Show map without login prompt
        console.log('Auto-login successful');
        document.getElementById('logoutBtn').style.display = 'block';
        initializeMap();
        return;
      } catch (e) {
        // Stored password is invalid/stale, clear it
        console.log('Auto-login failed:', e);
        localStorage.removeItem('mapAuth');
        sessionStorage.removeItem('mapAuth');
      }
    }
    
    // No valid session - show login or use plain data
    if (isEncrypted) {
      console.log('Showing login modal...');
      let modal = document.getElementById('loginModal');
      console.log('Modal before display change:', modal, 'display:', modal ? modal.style.display : 'null');
      modal.style.display = 'flex';
      console.log('Modal after display change:', modal.style.display);
      setTimeout(() => document.getElementById('mapPassword').focus(), 100);
    } else {
      // No encryption, parse data directly
      console.log('No encryption, loading data directly');
      devices = JSON.parse(encryptedDevices);
      edges = JSON.parse(encryptedEdges);
      initializeMap();
    }
  }

  // Initialize map with data
  function initializeMap() {
    console.log('initializeMap called');
    // Wait for the DOM and map to be ready - check if Folium map exists
    var mapContainer = document.querySelector('.folium-map');
    if (!mapContainer || !window[mapContainer.id]) {
      console.log('Map not ready yet, waiting...');
      setTimeout(initializeMap, 100);
      return;
    }
    console.log('Map is ready, initializing...');

    // Create set of offline node IDs for quick lookup
    var offlineNodeIdsSet = new Set();
    offlineNodeIds.forEach(function(id) {
      offlineNodeIdsSet.add(id.toUpperCase());
    });

    // Leaflet layers and lookup tables
    var edgesByNode = {};
    var allEdges = [];
    var maxEdgeCount = 0;

    // Compute max count for weighting
    edges.forEach(function(e) {
    if (typeof e.count === "number" && e.count > maxEdgeCount) {
      maxEdgeCount = e.count;
    }
  });
  if (maxEdgeCount < 1) { maxEdgeCount = 1; }

  function weightForCount(c) {
    c = c || 1;
    if (maxEdgeCount <= 1) { return 2; }
    return 1 + 4 * (Math.log(1 + c) / Math.log(1 + maxEdgeCount));
  }

  function buildLabel(d) {
    var name = d.DeviceName || d.ID;
    var loc = d.Location || "";
    if (loc) {
      return name + " — " + loc + "<br>ID: " + d.ID;
    }
    return name + "<br>ID: " + d.ID;
  }

  // Create edges (lines)
  edges.forEach(function(e) {
    var w = weightForCount(e.count);
    
    // Check if either endpoint is offline
    var isOfflineEdge = offlineNodeIdsSet.has(e.frm) || offlineNodeIdsSet.has(e.to);
    
    var line = L.polyline(
      [[e.lat_from, e.lon_from], [e.lat_to, e.lon_to]],
      {
        color: "#3388ff",
        weight: w,
        opacity: isOfflineEdge ? 0 : 0.5  // Hide edges connected to offline nodes
      }
    );
    line.baseWeight = w;
    line.fromId = e.frm;
    line.toId = e.to;
    line.isOfflineEdge = isOfflineEdge;
    allEdges.push(line);
    if (!edgesByNode[e.frm]) { edgesByNode[e.frm] = []; }
    if (!edgesByNode[e.to]) { edgesByNode[e.to] = []; }
    edgesByNode[e.frm].push(line);
    edgesByNode[e.to].push(line);
    line.addTo(mapObj);
  });

  // Create a mapping of lat/lng to device ID for marker click handling
  var coordToDeviceId = {};
  devices.forEach(function(d) {
    if (d.Latitude && d.Longitude) {
      var key = d.Latitude.toFixed(6) + ',' + d.Longitude.toFixed(6);
      coordToDeviceId[key] = d.ID_upper;
    }
  });

  // Add click handlers to all markers
  mapObj.eachLayer(function(layer) {
    if (layer instanceof L.Marker) {
      layer.on('click', function(e) {
        // Get the device ID from coordinates
        var lat = this.getLatLng().lat.toFixed(6);
        var lng = this.getLatLng().lng.toFixed(6);
        var key = lat + ',' + lng;
        var deviceId = coordToDeviceId[key];
        if (deviceId) {
          highlightDevice(deviceId);
        }
      });
    }
  });

  var selectedId = null;

  function resetHighlight() {
    allEdges.forEach(function(line) {
      // If edge is connected to offline node, hide it by default
      var defaultOpacity = line.isOfflineEdge ? 0 : 0.5;
      line.setStyle({
        color: "#3388ff",
        opacity: defaultOpacity,
        weight: line.baseWeight
      });
    });
    selectedId = null;
  }

  function highlightDevice(idUpper) {
    // If clicking on the already selected device, deselect it
    if (selectedId === idUpper) {
      resetHighlight();
      return;
    }
    
    resetHighlight();
    selectedId = idUpper;
    var lines = edgesByNode[idUpper] || [];
    lines.forEach(function(line) {
      line.setStyle({
        color: "#000000",
        opacity: 0.9
      });
    });
  }

  function focusOnDevice(idUpper) {
    // Find the device in our data
    var device = null;
    for (var i = 0; i < devices.length; i++) {
      if (devices[i].ID_upper === idUpper) {
        device = devices[i];
        break;
      }
    }
    if (device && device.Latitude && device.Longitude) {
      mapObj.setView([device.Latitude, device.Longitude], Math.max(mapObj.getZoom(), 13));
      highlightDevice(idUpper);
    }
  }

  // Search logic
  var searchInput = document.getElementById("nodeSearch");
  var resultsDiv = document.getElementById("searchResults");

  function renderResults(matches) {
    resultsDiv.innerHTML = "";
    matches.slice(0, 50).forEach(function(d) {
      var div = document.createElement("div");
      div.className = "search-result";
      div.innerHTML = buildLabel(d);
      div.onclick = function() {
        focusOnDevice(d.ID_upper);
      };
      resultsDiv.appendChild(div);
    });
  }

  function filterDevices(query) {
    var q = (query || "").trim().toLowerCase();
    if (!q) {
      resultsDiv.innerHTML = "";
      resetHighlight();
      return;
    }

    var matches = [];
    devices.forEach(function(d) {
      var haystack = (d.ID + " " +
                      (d.DeviceName || "") + " " +
                      (d.Location || "")).toLowerCase();
      if (haystack.indexOf(q) !== -1) {
        matches.push(d);
      }
    });
    renderResults(matches);
  }

  searchInput.addEventListener("input", function() {
    filterDevices(this.value);
  });

  // Offline nodes display
  var offlineListDiv = document.getElementById("offlineList");
  
  function renderOfflineNodes() {
    offlineListDiv.innerHTML = "";
    
    if (!offlineNodes || offlineNodes.length === 0) {
      offlineListDiv.innerHTML = "<div style='color: #999; padding: 4px;'>No offline nodes</div>";
      return;
    }
    
    offlineNodes.forEach(function(node) {
      var name = node[0];
      var nodeId = node[1];
      
      var div = document.createElement("div");
      div.className = "offline-item";
      
      var nameDiv = document.createElement("div");
      nameDiv.className = "offline-name";
      nameDiv.textContent = name;
      
      var idDiv = document.createElement("div");
      idDiv.className = "offline-id";
      idDiv.textContent = "Node ID: " + nodeId;
      
      div.appendChild(nameDiv);
      div.appendChild(idDiv);
      
      div.onclick = function() {
        // Try to find device by node ID
        var deviceIdUpper = nodeId.toUpperCase().trim();
        focusOnDevice(deviceIdUpper);
      };
      
      offlineListDiv.appendChild(div);
    });
  }
  
  renderOfflineNodes();
  } // End initializeMap

  // Start auth check when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkAuth);
  } else {
    checkAuth();
  }

</script>
"""

    # Replace placeholders with actual JSON/map name
    search_html = (search_html
                   .replace("__DEVICES_JSON__", devices_json)
                   .replace("__EDGES_JSON__", edges_json)
                   .replace("__IS_ENCRYPTED__", is_encrypted)
                   .replace("__OFFLINE_NODES_JSON__", offline_nodes_json)
                   .replace("__OFFLINE_NODE_IDS_JSON__", offline_node_ids_json)
                   .replace("__MAP_NAME__", map_name))

    m.get_root().html.add_child(folium.Element(search_html))
    m.save(out_html)
    print(f"Wrote {out_html}")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", required=True, help="Path to paths.csv/tsv.")
    ap.add_argument("--devices", required=True, help="Path to devices.xlsx or devices.csv (ID, Latitude, Longitude[, Type]).")
    ap.add_argument("--labels", required=False, help="Path to labels.csv (ID, DeviceName, Location).")
    ap.add_argument("--sep", choices=["auto", "comma", "tab"], default="auto", help="Separator mode for paths file.")
    ap.add_argument("--out", default="routes_map.html", help="Output HTML map file.")
    ap.add_argument("--sample", type=int, default=None, help="Use only first N rows of path log.")
    ap.add_argument("--aggregate", dest="aggregate", action="store_true", help="Aggregate edges and weight by count.")
    ap.add_argument("--no-aggregate", dest="aggregate", action="store_false", help="Draw every individual path (heavy).")
    ap.add_argument("--min-count", type=int, default=1, help="Only draw edges seen at least this many times (aggregate mode).")
    ap.add_argument("--show-markers", dest="show_markers", action="store_true", help="Include device markers.")
    ap.add_argument("--hide-markers", dest="show_markers", action="store_false", help="Hide device markers.")
    ap.add_argument("--center", dest="center_id", default=None, help="Device ID to center the map on.")
    ap.add_argument("--zoom", dest="zoom_start", type=int, default=9, help="Initial zoom level.")
    ap.add_argument("--skip-offline", dest="skip_offline", action="store_true", help="Skip fetching offline nodes from ThingsBoard.")
    ap.add_argument("--password", default=None, help="Password for data obfuscation (optional).")
    ap.set_defaults(aggregate=True, show_markers=True, skip_offline=False)
    args = ap.parse_args()

    devices = load_devices(args.devices)

    # If labels are provided, merge onto devices by ID (case-insensitive)
    if args.labels:
        labels = load_labels(args.labels)
        devices = devices.join(labels[["DeviceName", "Location"]], how="left")

    paths = load_paths(args.paths, sample=args.sample, sep_mode=args.sep)
    edges = build_edges(paths)
    edges_xy = add_coords(edges, devices)

    # Diagnostics
    total_edges = len(edges)
    edges_with_xy = len(edges_xy)
    missing = total_edges - edges_with_xy
    if missing > 0:
        involved_ids = set(edges["frm"]).union(set(edges["to"]))
        known_ids = set(devices.index)
        missing_ids = sorted([i for i in involved_ids if i not in known_ids])
        print(f"WARNING: {missing} edges dropped due to missing coordinates.")
        if len(missing_ids) <= 50:
            print("Missing device IDs:", ", ".join(missing_ids))
        else:
            print(f"{len(missing_ids)} device IDs lack coordinates (not listed).")

    # Fetch offline nodes from ThingsBoard
    offline_nodes = None
    if not args.skip_offline:
        try:
            print("Fetching offline nodes from ThingsBoard...")
            URL = "https://live2.innovateauckland.nz/dashboard/baafc030-dfa9-11ec-bc22-bb13277b57e1?publicId=8d688430-d497-11ec-92a2-f938b249c783"
            # Use longer wait time in CI environments (detect by checking for CI env var)
            wait_time = 10 if os.environ.get('CI') else 5
            offline_nodes = thingsboard_scraper.get_offline_nodes(URL, wait_time=wait_time, headless=True)
            if offline_nodes:
                print(f"Found {len(offline_nodes)} offline nodes")
            else:
                print("No offline nodes found")
        except Exception as e:
            print(f"WARNING: Failed to fetch offline nodes: {e}")
            import traceback
            traceback.print_exc()
            offline_nodes = None

    make_map(devices, edges_xy, args.out,
             aggregate=args.aggregate,
             min_count=args.min_count,
             show_markers=args.show_markers,
             center_id=args.center_id,
             zoom_start=args.zoom_start,
             offline_nodes=offline_nodes,
             password=args.password)


if __name__ == "__main__":
    main()
