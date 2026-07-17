// ===========================================================================
// Map application — injected into the generated HTML at build time.
//
// Placeholders like __DEVICES_JSON__ are replaced by Python with real data
// before the HTML is saved. The user's browser then handles everything:
// password auth, decryption, rendering edges/markers, and search.
// ===========================================================================

// --- Data injected by Python (placeholders replaced at build time) ---
var encryptedDevices = "__DEVICES_JSON__";
var encryptedEdges = "__EDGES_JSON__";
var isEncrypted = __IS_ENCRYPTED__;
var offlineNodes = __OFFLINE_NODES_JSON__;
var offlineNodeIds = __OFFLINE_NODE_IDS_JSON__;

var mapObj = null;   // Leaflet map instance (set once map is ready)
var devices = null;  // Decrypted device array
var edges = null;    // Decrypted edge array

// ===========================================================================
// Authentication — XOR decrypt, login/logout, session persistence
// ===========================================================================

/**
 * Reverse the Python XOR obfuscation.
 * Decodes base64, then XORs each byte with the cycling password.
 */
function deobfuscate(base64Data, password) {
  var encrypted = atob(base64Data);
  var encoder = new TextEncoder();
  var keyBytes = encoder.encode(password);

  var decrypted = "";
  for (var i = 0; i < encrypted.length; i++) {
    decrypted += String.fromCharCode(encrypted.charCodeAt(i) ^ keyBytes[i % keyBytes.length]);
  }
  return decrypted;
}

/** Try to decrypt data with the entered password. */
function attemptLogin() {
  var password = document.getElementById("mapPassword").value;
  var remember = document.getElementById("rememberMe").checked;
  var errorDiv = document.getElementById("loginError");

  if (!password) {
    errorDiv.textContent = "Please enter a password";
    errorDiv.style.display = "block";
    return;
  }

  try {
    // If the password is wrong, JSON.parse will fail on the garbled output
    devices = JSON.parse(deobfuscate(encryptedDevices, password));
    edges = JSON.parse(deobfuscate(encryptedEdges, password));

    // Store password so the user doesn't have to re-enter it on refresh
    var storage = remember ? localStorage : sessionStorage;
    storage.setItem("mapAuth", btoa(password));

    document.getElementById("loginModal").style.display = "none";
    document.getElementById("logoutBtn").style.display = "block";
    initializeMap();
  } catch (e) {
    errorDiv.textContent = "Incorrect password. Please try again.";
    errorDiv.style.display = "block";
    document.getElementById("mapPassword").value = "";
    document.getElementById("mapPassword").focus();
  }
}

function logout() {
  localStorage.removeItem("mapAuth");
  sessionStorage.removeItem("mapAuth");
  location.reload();
}

// Submit password on Enter key
document.addEventListener("DOMContentLoaded", function () {
  var passwordInput = document.getElementById("mapPassword");
  if (passwordInput) {
    passwordInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") attemptLogin();
    });
  }
});

/**
 * On page load: try to auto-login from a stored session,
 * show the login modal if encrypted, or load data directly if not.
 */
function checkAuth() {
  var storedAuth = localStorage.getItem("mapAuth") || sessionStorage.getItem("mapAuth");

  // Try auto-login with previously stored password
  if (storedAuth && isEncrypted) {
    try {
      var password = atob(storedAuth);
      devices = JSON.parse(deobfuscate(encryptedDevices, password));
      edges = JSON.parse(deobfuscate(encryptedEdges, password));

      document.getElementById("logoutBtn").style.display = "block";
      initializeMap();
      return;
    } catch (e) {
      // Stored password is stale — clear it and show login
      localStorage.removeItem("mapAuth");
      sessionStorage.removeItem("mapAuth");
    }
  }

  if (isEncrypted) {
    // Show login modal
    document.getElementById("loginModal").style.display = "flex";
    setTimeout(function () {
      document.getElementById("mapPassword").focus();
    }, 100);
  } else {
    // No encryption — parse data directly
    devices = JSON.parse(encryptedDevices);
    edges = JSON.parse(encryptedEdges);
    initializeMap();
  }
}

// ===========================================================================
// Map initialisation — edges, markers, click handlers
// ===========================================================================

function initializeMap() {
  // Folium creates the map asynchronously — wait until it's ready
  var mapContainer = document.querySelector(".folium-map");
  if (!mapContainer || !window[mapContainer.id]) {
    setTimeout(initializeMap, 100);
    return;
  }

  mapObj = window[mapContainer.id];

  // Build a quick-lookup set of offline node IDs
  var offlineNodeIdsSet = new Set();
  offlineNodeIds.forEach(function (id) {
    offlineNodeIdsSet.add(id.toUpperCase());
  });

  // --- Draw edges (lines between nodes) ---

  var edgesByNode = {};  // nodeId -> [lines connected to that node]
  var allEdges = [];
  var maxEdgeCount = 0;

  // Find the highest edge count (used to scale line thickness)
  edges.forEach(function (e) {
    if (typeof e.count === "number" && e.count > maxEdgeCount) {
      maxEdgeCount = e.count;
    }
  });
  if (maxEdgeCount < 1) maxEdgeCount = 1;

  // Scale line weight logarithmically so high-count edges don't dominate
  function weightForCount(c) {
    c = c || 1;
    if (maxEdgeCount <= 1) return 2;
    return 1 + 4 * (Math.log(1 + c) / Math.log(1 + maxEdgeCount));
  }

  edges.forEach(function (e) {
    var w = weightForCount(e.count);
    var isOfflineEdge = offlineNodeIdsSet.has(e.frm) || offlineNodeIdsSet.has(e.to);

    var line = L.polyline(
      [[e.lat_from, e.lon_from], [e.lat_to, e.lon_to]],
      {
        color: "#3388ff",
        weight: w,
        opacity: isOfflineEdge ? 0 : 0.5,  // Hide edges to offline nodes
      }
    );

    // Store metadata on the line for highlighting later
    line.baseWeight = w;
    line.fromId = e.frm;
    line.toId = e.to;
    line.count = e.count;
    line.isOfflineEdge = isOfflineEdge;

    allEdges.push(line);

    // Index edges by both endpoints so we can highlight all edges for a device
    if (!edgesByNode[e.frm]) edgesByNode[e.frm] = [];
    if (!edgesByNode[e.to]) edgesByNode[e.to] = [];
    edgesByNode[e.frm].push(line);
    edgesByNode[e.to].push(line);

    line.addTo(mapObj);
  });

  // --- Connect Folium markers to our click handler ---
  // Folium markers don't carry custom data, so we map lat/lng back to device ID
  var coordToDeviceId = {};
  var idToDevice = {};  // ID_upper -> device (for path panel neighbour names)
  devices.forEach(function (d) {
    idToDevice[d.ID_upper] = d;
    if (d.Latitude && d.Longitude) {
      var key = d.Latitude.toFixed(6) + "," + d.Longitude.toFixed(6);
      coordToDeviceId[key] = d.ID_upper;
    }
  });

  mapObj.eachLayer(function (layer) {
    if (layer instanceof L.Marker) {
      layer.on("click", function () {
        var lat = this.getLatLng().lat.toFixed(6);
        var lng = this.getLatLng().lng.toFixed(6);
        var deviceId = coordToDeviceId[lat + "," + lng];
        if (deviceId) highlightDevice(deviceId);
      });
    }
  });

  // --- Edge highlighting + paths panel (click a device to see its connections) ---

  var selectedId = null;         // currently selected device
  var selectedRowLine = null;    // single edge isolated via a path-row click

  var pathsPanel = document.getElementById("pathsPanel");
  var pathsTitle = document.getElementById("pathsTitle");
  var pathsList = document.getElementById("pathsList");
  var pathsCollapseBtn = document.getElementById("pathsCollapseBtn");
  var pathsCloseBtn = document.getElementById("pathsCloseBtn");

  /** Reset every edge back to its default blue/dim style. */
  function styleEdgesDefault(dimUnselected) {
    allEdges.forEach(function (line) {
      line.setStyle({
        color: "#3388ff",
        opacity: line.isOfflineEdge ? 0 : (dimUnselected ? 0.2 : 0.5),
        weight: line.baseWeight,
      });
    });
  }

  /** Black-highlight every (online) edge connected to a node — the full node view. */
  function styleNodeEdges(idUpper) {
    (edgesByNode[idUpper] || []).forEach(function (line) {
      if (line.isOfflineEdge) return;  // offline edges stay hidden
      line.setStyle({ color: "#000000", opacity: 0.9, weight: line.baseWeight });
    });
  }

  function displayName(dev, fallbackId) {
    if (dev && dev.DeviceName) return dev.DeviceName;
    if (dev && dev.ID) return dev.ID;
    return fallbackId;
  }

  function resetHighlight() {
    styleEdgesDefault(false);
    selectedId = null;
    selectedRowLine = null;
    pathsPanel.style.display = "none";
    pathsList.innerHTML = "";
  }

  /** Return from a single-edge isolation to the full node highlight. */
  function clearRowIsolation() {
    selectedRowLine = null;
    styleEdgesDefault(false);
    if (selectedId) styleNodeEdges(selectedId);
    pathsList.querySelectorAll(".path-row.selected").forEach(function (r) {
      r.classList.remove("selected");
    });
  }

  /** Isolate one edge on the map: dim all others, black just this one. */
  function isolateEdge(line, rowEl) {
    // Clicking the same row again returns to the full node view
    if (selectedRowLine === line) {
      clearRowIsolation();
      return;
    }
    styleEdgesDefault(true);
    line.setStyle({ color: "#000000", opacity: 0.95, weight: line.baseWeight + 1 });
    selectedRowLine = line;

    pathsList.querySelectorAll(".path-row.selected").forEach(function (r) {
      r.classList.remove("selected");
    });
    rowEl.classList.add("selected");
  }

  /** Populate and show the paths box for a selected device. */
  function renderPathsPanel(idUpper) {
    var lines = edgesByNode[idUpper] || [];

    // One descriptor per connected edge: direction, neighbour, count
    var rows = lines.map(function (line) {
      var outgoing = (line.fromId === idUpper);
      var otherId = outgoing ? line.toId : line.fromId;
      return {
        line: line,
        outgoing: outgoing,
        name: displayName(idToDevice[otherId], otherId),
        count: line.count || 0,
        offline: line.isOfflineEdge,
      };
    });
    rows.sort(function (a, b) { return b.count - a.count; });

    pathsTitle.textContent =
      displayName(idToDevice[idUpper], idUpper) + "  •  " + rows.length +
      (rows.length === 1 ? " path" : " paths");

    pathsList.innerHTML = "";
    if (rows.length === 0) {
      var empty = document.createElement("div");
      empty.className = "paths-empty";
      empty.textContent = "No paths for this node";
      pathsList.appendChild(empty);
    } else {
      rows.forEach(function (r) {
        var row = document.createElement("div");
        row.className = "path-row" + (r.offline ? " offline" : "");

        var arrow = document.createElement("span");
        arrow.className = "path-arrow " + (r.outgoing ? "out" : "in");
        arrow.textContent = r.outgoing ? "→" : "←";

        var nameSpan = document.createElement("span");
        nameSpan.className = "path-name";
        nameSpan.textContent = r.name;

        var badge = document.createElement("span");
        badge.className = "path-count";
        badge.textContent = r.count;

        row.appendChild(arrow);
        row.appendChild(nameSpan);
        row.appendChild(badge);

        // Offline edges stay hidden on the map, so their rows aren't clickable
        if (!r.offline) {
          row.onclick = function () { isolateEdge(r.line, row); };
        }

        pathsList.appendChild(row);
      });
    }

    pathsPanel.classList.remove("collapsed");
    if (pathsCollapseBtn) pathsCollapseBtn.textContent = "▾";
    pathsPanel.style.display = "block";
  }

  function highlightDevice(idUpper) {
    // Toggle off if clicking the same device again
    if (selectedId === idUpper) {
      resetHighlight();
      return;
    }

    resetHighlight();
    selectedId = idUpper;

    styleNodeEdges(idUpper);
    renderPathsPanel(idUpper);
  }

  // Collapse chevron hides the list but keeps the node selected; ✕ closes fully.
  if (pathsCollapseBtn) {
    pathsCollapseBtn.onclick = function () {
      var collapsed = pathsPanel.classList.toggle("collapsed");
      pathsCollapseBtn.textContent = collapsed ? "▸" : "▾";
    };
  }
  if (pathsCloseBtn) {
    pathsCloseBtn.onclick = function () { resetHighlight(); };
  }

  function focusOnDevice(idUpper) {
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

  // ===========================================================================
  // Search — filter devices by ID, name, or location
  // ===========================================================================

  var searchInput = document.getElementById("nodeSearch");
  var resultsDiv = document.getElementById("searchResults");

  /** Build a search result label using safe DOM methods (no innerHTML with user data). */
  function buildLabelElement(d) {
    var container = document.createElement("span");
    container.appendChild(document.createTextNode(d.DeviceName || d.ID));
    if (d.Location) {
      container.appendChild(document.createTextNode(" — " + d.Location));
    }
    container.appendChild(document.createElement("br"));
    container.appendChild(document.createTextNode("ID: " + d.ID));
    return container;
  }

  function renderResults(matches) {
    resultsDiv.innerHTML = "";
    matches.slice(0, 50).forEach(function (d) {
      var div = document.createElement("div");
      div.className = "search-result";
      div.appendChild(buildLabelElement(d));
      div.onclick = function () { focusOnDevice(d.ID_upper); };
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
    devices.forEach(function (d) {
      var haystack = (d.ID + " " + (d.DeviceName || "") + " " + (d.Location || "")).toLowerCase();
      if (haystack.indexOf(q) !== -1) matches.push(d);
    });
    renderResults(matches);
  }

  searchInput.addEventListener("input", function () {
    filterDevices(this.value);
  });

  // ===========================================================================
  // Offline nodes panel
  // ===========================================================================

  var offlineListDiv = document.getElementById("offlineList");

  function renderOfflineNodes() {
    offlineListDiv.innerHTML = "";

    if (!offlineNodes || offlineNodes.length === 0) {
      offlineListDiv.innerHTML = '<div style="color: #999; padding: 4px;">No offline nodes</div>';
      return;
    }

    offlineNodes.forEach(function (node) {
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

      div.onclick = function () {
        focusOnDevice(nodeId.toUpperCase().trim());
      };

      offlineListDiv.appendChild(div);
    });
  }

  renderOfflineNodes();

  // ===========================================================================
  // Timestamp — show when the offline data was last scraped
  // ===========================================================================

  var scrapeTime = new Date("__SCRAPE_TIMESTAMP__");
  var formatted = scrapeTime.toLocaleString("en-NZ", {
    timeZone: "Pacific/Auckland",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  document.getElementById("lastUpdated").textContent = formatted;
}

// ===========================================================================
// Bootstrap — kick off auth check when the page is ready
// ===========================================================================

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", checkAuth);
} else {
  checkAuth();
}
