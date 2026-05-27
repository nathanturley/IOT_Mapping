// Injected by Python at build time
var encryptedDevices = "__DEVICES_JSON__";
var encryptedEdges = "__EDGES_JSON__";
var isEncrypted = __IS_ENCRYPTED__;
var offlineNodes = __OFFLINE_NODES_JSON__;
var offlineNodeIds = __OFFLINE_NODE_IDS_JSON__;
var mapObj = null;

var devices = null;
var edges = null;

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
    var devicesJson = deobfuscate(encryptedDevices, password);
    var edgesJson = deobfuscate(encryptedEdges, password);

    devices = JSON.parse(devicesJson);
    edges = JSON.parse(edgesJson);

    var authToken = btoa(password);
    var storage = remember ? localStorage : sessionStorage;
    storage.setItem("mapAuth", authToken);

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

document.addEventListener("DOMContentLoaded", function () {
  var passwordInput = document.getElementById("mapPassword");
  if (passwordInput) {
    passwordInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") {
        attemptLogin();
      }
    });
  }
});

function checkAuth() {
  var storedAuth = localStorage.getItem("mapAuth") || sessionStorage.getItem("mapAuth");

  if (storedAuth && isEncrypted) {
    try {
      var password = atob(storedAuth);
      var devicesJson = deobfuscate(encryptedDevices, password);
      var edgesJson = deobfuscate(encryptedEdges, password);

      devices = JSON.parse(devicesJson);
      edges = JSON.parse(edgesJson);

      document.getElementById("logoutBtn").style.display = "block";
      initializeMap();
      return;
    } catch (e) {
      localStorage.removeItem("mapAuth");
      sessionStorage.removeItem("mapAuth");
    }
  }

  if (isEncrypted) {
    var modal = document.getElementById("loginModal");
    modal.style.display = "flex";
    setTimeout(function () {
      document.getElementById("mapPassword").focus();
    }, 100);
  } else {
    devices = JSON.parse(encryptedDevices);
    edges = JSON.parse(encryptedEdges);
    initializeMap();
  }
}

function initializeMap() {
  var mapContainer = document.querySelector(".folium-map");
  if (!mapContainer || !window[mapContainer.id]) {
    setTimeout(initializeMap, 100);
    return;
  }

  mapObj = window[mapContainer.id];

  var offlineNodeIdsSet = new Set();
  offlineNodeIds.forEach(function (id) {
    offlineNodeIdsSet.add(id.toUpperCase());
  });

  var edgesByNode = {};
  var allEdges = [];
  var maxEdgeCount = 0;

  edges.forEach(function (e) {
    if (typeof e.count === "number" && e.count > maxEdgeCount) {
      maxEdgeCount = e.count;
    }
  });
  if (maxEdgeCount < 1) {
    maxEdgeCount = 1;
  }

  function weightForCount(c) {
    c = c || 1;
    if (maxEdgeCount <= 1) {
      return 2;
    }
    return 1 + 4 * (Math.log(1 + c) / Math.log(1 + maxEdgeCount));
  }

  function buildLabelElement(d) {
    var container = document.createElement("span");

    var nameText = document.createTextNode(d.DeviceName || d.ID);
    container.appendChild(nameText);

    if (d.Location) {
      container.appendChild(document.createTextNode(" — " + d.Location));
    }

    var br = document.createElement("br");
    container.appendChild(br);

    var idText = document.createTextNode("ID: " + d.ID);
    container.appendChild(idText);

    return container;
  }

  edges.forEach(function (e) {
    var w = weightForCount(e.count);
    var isOfflineEdge = offlineNodeIdsSet.has(e.frm) || offlineNodeIdsSet.has(e.to);

    var line = L.polyline(
      [[e.lat_from, e.lon_from], [e.lat_to, e.lon_to]],
      {
        color: "#3388ff",
        weight: w,
        opacity: isOfflineEdge ? 0 : 0.5,
      }
    );
    line.baseWeight = w;
    line.fromId = e.frm;
    line.toId = e.to;
    line.isOfflineEdge = isOfflineEdge;
    allEdges.push(line);
    if (!edgesByNode[e.frm]) {
      edgesByNode[e.frm] = [];
    }
    if (!edgesByNode[e.to]) {
      edgesByNode[e.to] = [];
    }
    edgesByNode[e.frm].push(line);
    edgesByNode[e.to].push(line);
    line.addTo(mapObj);
  });

  var coordToDeviceId = {};
  devices.forEach(function (d) {
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
        var key = lat + "," + lng;
        var deviceId = coordToDeviceId[key];
        if (deviceId) {
          highlightDevice(deviceId);
        }
      });
    }
  });

  var selectedId = null;

  function resetHighlight() {
    allEdges.forEach(function (line) {
      var defaultOpacity = line.isOfflineEdge ? 0 : 0.5;
      line.setStyle({
        color: "#3388ff",
        opacity: defaultOpacity,
        weight: line.baseWeight,
      });
    });
    selectedId = null;
  }

  function highlightDevice(idUpper) {
    if (selectedId === idUpper) {
      resetHighlight();
      return;
    }

    resetHighlight();
    selectedId = idUpper;
    var lines = edgesByNode[idUpper] || [];
    lines.forEach(function (line) {
      line.setStyle({
        color: "#000000",
        opacity: 0.9,
      });
    });
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

  var searchInput = document.getElementById("nodeSearch");
  var resultsDiv = document.getElementById("searchResults");

  function renderResults(matches) {
    resultsDiv.innerHTML = "";
    matches.slice(0, 50).forEach(function (d) {
      var div = document.createElement("div");
      div.className = "search-result";
      div.appendChild(buildLabelElement(d));
      div.onclick = function () {
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
    devices.forEach(function (d) {
      var haystack = (d.ID + " " + (d.DeviceName || "") + " " + (d.Location || "")).toLowerCase();
      if (haystack.indexOf(q) !== -1) {
        matches.push(d);
      }
    });
    renderResults(matches);
  }

  searchInput.addEventListener("input", function () {
    filterDevices(this.value);
  });

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
        var deviceIdUpper = nodeId.toUpperCase().trim();
        focusOnDevice(deviceIdUpper);
      };

      offlineListDiv.appendChild(div);
    });
  }

  renderOfflineNodes();

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

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", checkAuth);
} else {
  checkAuth();
}
