const WORLD_LAT_LIMIT = 85.05112878;

const state = {
  geojson: null,
  bounds: null,
  featureCount: 0,
  map: null,
  geoLayer: null,
  boundsLayer: null,
  gridLayer: null,
};

const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const minZoomInput = document.getElementById("minZoom");
const maxZoomInput = document.getElementById("maxZoom");
const previewZoomInput = document.getElementById("previewZoom");
const previewZoomValue = document.getElementById("previewZoomValue");
const messages = document.getElementById("messages");
const zoomTableBody = document.getElementById("zoomTableBody");
const featureCountEl = document.getElementById("featureCount");
const boundsEl = document.getElementById("boundsValue");
const tilesMinEl = document.getElementById("tilesMin");
const tilesMaxEl = document.getElementById("tilesMax");
const currentPreviewZoomEl = document.getElementById("currentPreviewZoom");
const visibilityStateEl = document.getElementById("visibilityState");

function initializeMap() {
  state.map = L.map("map", { zoomControl: true }).setView([20, 0], 2);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
}

function showMessage(text, isError = false) {
  messages.textContent = text;
  messages.classList.toggle("error", Boolean(isError));
}

function clampZoom(value) {
  return Math.max(0, Math.min(22, Number.parseInt(value, 10) || 0));
}

function getZoomRange() {
  const minZoom = clampZoom(minZoomInput.value);
  const maxZoom = clampZoom(maxZoomInput.value);

  if (minZoom > maxZoom) {
    return null;
  }

  return { minZoom, maxZoom };
}

function setLayerVisibility(layer, visible) {
  if (!layer || !state.map) {
    return;
  }

  const hasLayer = state.map.hasLayer(layer);
  if (visible && !hasLayer) {
    layer.addTo(state.map);
  }

  if (!visible && hasLayer) {
    layer.remove();
  }
}

function updateDataVisibility(range, previewZoom) {
  if (!state.geoLayer || !state.boundsLayer) {
    visibilityStateEl.textContent = "No data";
    return;
  }

  const inRange = previewZoom >= range.minZoom && previewZoom <= range.maxZoom;
  setLayerVisibility(state.geoLayer, inRange);
  setLayerVisibility(state.boundsLayer, inRange);

  visibilityStateEl.textContent = inRange
    ? `Visible at z${previewZoom}`
    : `Hidden at z${previewZoom}`;
}

function countFeatures(geojson) {
  if (geojson.type === "FeatureCollection") {
    return geojson.features?.length || 0;
  }

  if (geojson.type === "Feature") {
    return 1;
  }

  return 1;
}

function flattenGeometryCoordinates(geometry, output) {
  if (!geometry) {
    return;
  }

  const { type, coordinates, geometries } = geometry;

  if (type === "GeometryCollection") {
    (geometries || []).forEach((g) => flattenGeometryCoordinates(g, output));
    return;
  }

  function scanCoordinates(value) {
    if (!Array.isArray(value)) {
      return;
    }

    if (typeof value[0] === "number" && typeof value[1] === "number") {
      output.push([value[0], value[1]]);
      return;
    }

    value.forEach(scanCoordinates);
  }

  scanCoordinates(coordinates);
}

function computeBounds(geojson) {
  let minLon = 180;
  let minLat = 90;
  let maxLon = -180;
  let maxLat = -90;
  let found = false;

  function consumeFeature(feature) {
    const points = [];
    flattenGeometryCoordinates(feature.geometry, points);
    points.forEach(([lon, lat]) => {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
        return;
      }

      minLon = Math.min(minLon, lon);
      maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      found = true;
    });
  }

  if (geojson.type === "FeatureCollection") {
    (geojson.features || []).forEach(consumeFeature);
  } else if (geojson.type === "Feature") {
    consumeFeature(geojson);
  } else {
    consumeFeature({ geometry: geojson });
  }

  if (!found) {
    return null;
  }

  return {
    minLon: Math.max(-180, minLon),
    minLat: Math.max(-90, minLat),
    maxLon: Math.min(180, maxLon),
    maxLat: Math.min(90, maxLat),
  };
}

function lonToTileX(lon, zoom) {
  const normalized = (lon + 180) / 360;
  const count = 2 ** zoom;
  return Math.floor(normalized * count);
}

function latToTileY(lat, zoom) {
  const clamped = Math.max(-WORLD_LAT_LIMIT, Math.min(WORLD_LAT_LIMIT, lat));
  const radians = (clamped * Math.PI) / 180;
  const value =
    (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2;
  const count = 2 ** zoom;
  return Math.floor(value * count);
}

function tileXToLon(x, z) {
  return (x / 2 ** z) * 360 - 180;
}

function tileYToLat(y, z) {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** z;
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

function estimateTileCoverage(bounds, zoom) {
  const tileCount = 2 ** zoom;
  const xMin = Math.max(0, Math.min(tileCount - 1, lonToTileX(bounds.minLon, zoom)));
  const xMax = Math.max(0, Math.min(tileCount - 1, lonToTileX(bounds.maxLon, zoom)));
  const yMin = Math.max(0, Math.min(tileCount - 1, latToTileY(bounds.maxLat, zoom)));
  const yMax = Math.max(0, Math.min(tileCount - 1, latToTileY(bounds.minLat, zoom)));

  const width = Math.max(0, xMax - xMin + 1);
  const height = Math.max(0, yMax - yMin + 1);

  return {
    xMin,
    xMax,
    yMin,
    yMax,
    count: width * height,
    worldTiles: tileCount * tileCount,
  };
}

function updateSummary(range) {
  if (!state.bounds) {
    return;
  }

  const minEstimate = estimateTileCoverage(state.bounds, range.minZoom);
  const maxEstimate = estimateTileCoverage(state.bounds, range.maxZoom);

  featureCountEl.textContent = String(state.featureCount);
  boundsEl.textContent = `${state.bounds.minLon.toFixed(4)}, ${state.bounds.minLat.toFixed(4)} .. ${state.bounds.maxLon.toFixed(4)}, ${state.bounds.maxLat.toFixed(4)}`;
  tilesMinEl.textContent = minEstimate.count.toLocaleString();
  tilesMaxEl.textContent = maxEstimate.count.toLocaleString();
}

function updateZoomTable(range) {
  if (!state.bounds) {
    zoomTableBody.innerHTML =
      '<tr><td colspan="3" class="empty-row">Upload a file to see estimates.</td></tr>';
    return;
  }

  const rows = [];
  for (let z = range.minZoom; z <= range.maxZoom; z += 1) {
    const estimate = estimateTileCoverage(state.bounds, z);
    const share = (estimate.count / estimate.worldTiles) * 100;
    rows.push(`
      <tr>
        <td>${z}</td>
        <td>${estimate.count.toLocaleString()}</td>
        <td>${share.toFixed(6)}%</td>
      </tr>
    `);
  }

  zoomTableBody.innerHTML = rows.join("");
}

function refreshGrid() {
  if (!state.bounds || !state.map) {
    return;
  }

  const previewZoom = clampZoom(previewZoomInput.value);
  previewZoomValue.textContent = String(previewZoom);
  currentPreviewZoomEl.textContent = String(previewZoom);

  const estimate = estimateTileCoverage(state.bounds, previewZoom);

  if (state.gridLayer) {
    state.gridLayer.remove();
  }

  const group = L.layerGroup();
  for (let x = estimate.xMin; x <= estimate.xMax; x += 1) {
    for (let y = estimate.yMin; y <= estimate.yMax; y += 1) {
      const west = tileXToLon(x, previewZoom);
      const east = tileXToLon(x + 1, previewZoom);
      const north = tileYToLat(y, previewZoom);
      const south = tileYToLat(y + 1, previewZoom);
      L.rectangle(
        [
          [south, west],
          [north, east],
        ],
        {
          color: "#e27d34",
          weight: 1,
          fillColor: "#e27d34",
          fillOpacity: 0.08,
          interactive: false,
        }
      ).addTo(group);
    }
  }

  state.gridLayer = group.addTo(state.map);
}

function refreshAll() {
  const range = getZoomRange();
  if (!range) {
    showMessage("Min zoom cannot be greater than max zoom.", true);
    return;
  }

  const previewZoom = clampZoom(previewZoomInput.value);
  const inRange = previewZoom >= range.minZoom && previewZoom <= range.maxZoom;
  const visibilitySummary = inRange ? "visible" : "hidden";
  showMessage(`Estimates updated. Data is ${visibilitySummary} at z${previewZoom}.`);
  updateSummary(range);
  updateZoomTable(range);
  refreshGrid();
  updateDataVisibility(range, previewZoom);
}

function drawGeojson() {
  if (!state.geojson || !state.bounds) {
    return;
  }

  if (state.geoLayer) {
    state.geoLayer.remove();
  }

  if (state.boundsLayer) {
    state.boundsLayer.remove();
  }

  state.geoLayer = L.geoJSON(state.geojson, {
    style: {
      color: "#0d7a64",
      weight: 2,
      fillOpacity: 0.15,
    },
    pointToLayer: (_feature, latlng) =>
      L.circleMarker(latlng, {
        radius: 4,
        color: "#0d7a64",
        fillColor: "#0d7a64",
        fillOpacity: 0.8,
      }),
  }).addTo(state.map);

  state.boundsLayer = L.rectangle(
    [
      [state.bounds.minLat, state.bounds.minLon],
      [state.bounds.maxLat, state.bounds.maxLon],
    ],
    {
      color: "#bf3f34",
      weight: 2,
      fillOpacity: 0,
      dashArray: "6 6",
      interactive: false,
    }
  ).addTo(state.map);

  state.map.fitBounds(state.boundsLayer.getBounds(), { padding: [20, 20] });
}

function loadGeoJSON(rawText) {
  let parsed;
  try {
    parsed = JSON.parse(rawText);
  } catch (_err) {
    showMessage("Could not parse file as JSON.", true);
    return;
  }

  if (!parsed || typeof parsed !== "object") {
    showMessage("GeoJSON content is empty or invalid.", true);
    return;
  }

  const validType = [
    "FeatureCollection",
    "Feature",
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
  ].includes(parsed.type);

  if (!validType) {
    showMessage("This file does not look like valid GeoJSON.", true);
    return;
  }

  const bounds = computeBounds(parsed);
  if (!bounds) {
    showMessage("No valid coordinates found in the GeoJSON file.", true);
    return;
  }

  state.geojson = parsed;
  state.bounds = bounds;
  state.featureCount = countFeatures(parsed);

  drawGeojson();
  refreshAll();
}

function wireEvents() {
  fileInput.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    file
      .text()
      .then(loadGeoJSON)
      .catch(() => showMessage("Could not read the selected file.", true));
  });

  [minZoomInput, maxZoomInput].forEach((input) => {
    input.addEventListener("input", refreshAll);
    input.addEventListener("change", refreshAll);
  });

  previewZoomInput.addEventListener("input", () => {
    const nextZoom = clampZoom(previewZoomInput.value);
    previewZoomValue.textContent = String(nextZoom);
    currentPreviewZoomEl.textContent = String(nextZoom);
    if (state.map && Math.round(state.map.getZoom()) !== nextZoom) {
      state.map.setZoom(nextZoom);
    }
    refreshAll();
  });

  state.map.on("zoomend", () => {
    const mapZoom = clampZoom(Math.round(state.map.getZoom()));
    if (clampZoom(previewZoomInput.value) !== mapZoom) {
      previewZoomInput.value = String(mapZoom);
      previewZoomValue.textContent = String(mapZoom);
      currentPreviewZoomEl.textContent = String(mapZoom);
    }

    const range = getZoomRange();
    if (!range) {
      return;
    }

    refreshGrid();
    updateDataVisibility(range, mapZoom);
    const inRange = mapZoom >= range.minZoom && mapZoom <= range.maxZoom;
    const visibilitySummary = inRange ? "visible" : "hidden";
    showMessage(`Map zoom z${mapZoom}. Data is ${visibilitySummary} for range ${range.minZoom}-${range.maxZoom}.`);
  });

  const preventDefaults = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, preventDefaults);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add("drag-over"));
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove("drag-over"));
  });

  dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) {
      return;
    }

    file
      .text()
      .then(loadGeoJSON)
      .catch(() => showMessage("Could not read the dropped file.", true));
  });

  document.getElementById("presetCli").addEventListener("click", () => {
    minZoomInput.value = "0";
    maxZoomInput.value = "10";
    previewZoomInput.value = "6";
    previewZoomValue.textContent = "6";
    refreshAll();
  });

  document.getElementById("presetNotebook").addEventListener("click", () => {
    minZoomInput.value = "4";
    maxZoomInput.value = "8";
    previewZoomInput.value = "6";
    previewZoomValue.textContent = "6";
    refreshAll();
  });
}

initializeMap();
wireEvents();
showMessage("Ready. Upload a GeoJSON file to begin.");
previewZoomValue.textContent = previewZoomInput.value;
