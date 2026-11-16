// Placeholder map for the demo client.
//
// Boxes come from regions.json, which is checked against gnssiw.regions.
// Colors for October 2026 are an illustrative pattern (hotspots fall after
// 4 Oct, controls stay near 1) so the slider works before the API is live.
// Set window.GNSSIW_API_BASE to the deployed ApiBaseUrl to overlay
// GET /hotspots. Serve this folder with `python3 -m http.server`
// (fetch of regions.json does not work from a file:// page).

const API_BASE = (window.GNSSIW_API_BASE || "").replace(/\/$/, "");
const MONTH = "2026-10";

const statusEl = document.getElementById("status");
const detailEl = document.getElementById("detail-body");
const listEl = document.getElementById("region-list");
const dayInput = document.getElementById("day");
const dayLabel = document.getElementById("day-label");
const subscribeForm = document.getElementById("subscribe");
const subscribeResult = document.getElementById("subscribe-result");

const map = L.map("map", { worldCopyJump: true }).setView([48, 20], 4);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 9,
  attribution: "&copy; OpenStreetMap",
}).addTo(map);

const layers = new globalThis.Map();
let regions = [];
let selectedId = "baltic";

function dateForDay(day) {
  return `${MONTH}-${String(day).padStart(2, "0")}`;
}

function colorFor(ratio) {
  if (ratio >= 0.8) return "#2f9e44";
  if (ratio >= 0.4) return "#f08c00";
  return "#e03131";
}

// Illustrative only. This is the shape of the October 2026 finding, not the measurement.
function illustrative(region, day) {
  const control = region.type === "control";
  let ratio = 1.05;
  if (!control) {
    ratio = day < 4 ? 0.85 : region.id === "baltic" ? 0.14 : 0.07;
  }
  const drop = !control && day >= 4;
  return {
    ratio,
    z: drop ? -3.4 : control ? 0.2 : -0.4,
    gpsjamOverlap: drop ? 0.46 : 0.02,
    risk: drop ? "High" : "Low",
    summary: drop
      ? `${region.name} is drawn red here so the slider can be demoed before live counts exist.`
      : `${region.name} is near its baseline in this placeholder.`,
    illustrative: true,
  };
}

function worstByRegion(hotspots) {
  const byRegion = new globalThis.Map();
  for (const row of hotspots) {
    const current = byRegion.get(row.regionId);
    if (!current || row.ratio < current.ratio) byRegion.set(row.regionId, row);
  }
  return byRegion;
}

async function liveHotspots(dateStr) {
  if (!API_BASE) return null;
  const response = await fetch(`${API_BASE}/hotspots?date=${dateStr}`);
  if (!response.ok) throw new Error(`GET /hotspots returned ${response.status}`);
  const payload = await response.json();
  return Array.isArray(payload.hotspots) ? payload.hotspots : [];
}

function readingFor(region, day, live) {
  const row = live && live.get(region.id);
  if (!row) return illustrative(region, day);
  return {
    ratio: Number(row.ratio),
    z: row.z,
    gpsjamOverlap: Number(row.gpsjamOverlap ?? 0),
    risk: row.risk || "Low",
    summary: row.summary || "",
    illustrative: false,
    provider: row.provider,
  };
}

function paint(live) {
  const day = Number(dayInput.value);
  const dateStr = dateForDay(day);
  dayLabel.textContent = dateStr;
  for (const region of regions) {
    const reading = readingFor(region, day, live);
    const layer = layers.get(region.id);
    layer.setStyle({ color: colorFor(reading.ratio), fillColor: colorFor(reading.ratio) });
    layer.reading = reading;
  }
  showDetail(selectedId);
  return dateStr;
}

function showDetail(regionId) {
  selectedId = regionId;
  const region = regions.find((item) => item.id === regionId);
  const layer = layers.get(regionId);
  if (!region || !layer) return;
  const reading = layer.reading;
  const zText = reading.z === null || reading.z === undefined ? "n/a" : Number(reading.z).toFixed(2);
  const source = reading.illustrative ? "Illustrative placeholder." : `Live ${reading.provider || ""} row.`;
  detailEl.innerHTML = `
    <p><strong>${region.name}</strong> · ${region.type}</p>
    <p>Ratio ${reading.ratio.toFixed(2)} · z ${zText}<br />
    GPSJam overlap ${(reading.gpsjamOverlap * 100).toFixed(0)}% · risk ${reading.risk}</p>
    <p>${reading.summary}</p>
    <p>${source}</p>`;
}

function addRegions(loaded) {
  regions = loaded;
  const bounds = [];
  for (const region of regions) {
    const corners = [
      [region.minLat, region.minLon],
      [region.maxLat, region.maxLon],
    ];
    const layer = L.rectangle(corners, { weight: 2, fillOpacity: 0.45 });
    layer.on("click", () => {
      showDetail(region.id);
      map.fitBounds(layer.getBounds(), { maxZoom: 5 });
    });
    layer.addTo(map);
    layers.set(region.id, layer);
    bounds.push(corners[0], corners[1]);

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = region.name.replace(" (control)", "");
    button.addEventListener("click", () => {
      showDetail(region.id);
      map.fitBounds(layer.getBounds(), { maxZoom: 5 });
    });
    listEl.appendChild(button);
  }
  // Open on the two hotspot seas. Buttons fly to the control regions.
  const story = regions.filter((region) => region.type === "hotspot");
  const storyBounds = [];
  for (const region of story) {
    storyBounds.push([region.minLat, region.minLon], [region.maxLat, region.maxLon]);
  }
  map.fitBounds(storyBounds.length ? storyBounds : bounds, { padding: [24, 24] });
  paint(null);
}

async function refresh() {
  const dateStr = dateForDay(Number(dayInput.value));
  let live = null;
  try {
    const hotspots = await liveHotspots(dateStr);
    if (hotspots && hotspots.length) {
      live = worstByRegion(hotspots);
      statusEl.textContent = `Live hotspots for ${dateStr}.`;
    } else if (hotspots) {
      statusEl.textContent = `API returned no hotspots for ${dateStr}. Showing the illustrative October pattern.`;
    } else {
      statusEl.textContent =
        "Illustrative October 2026 pattern. Set GNSSIW_API_BASE in index.html to load live hotspots.";
    }
  } catch (error) {
    statusEl.textContent = `Could not reach the API (${error.message}). Showing the illustrative pattern.`;
  }
  paint(live);
}

dayInput.addEventListener("input", () => {
  refresh();
});

subscribeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("email").value.trim();
  if (!API_BASE) {
    subscribeResult.textContent =
      "Subscription API is not configured. Set GNSSIW_API_BASE, then submit again.";
    return;
  }
  subscribeResult.textContent = "Sending…";
  try {
    const response = await fetch(`${API_BASE}/subscriptions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, minRisk: "High" }),
    });
    const payload = await response.json();
    if (!response.ok) {
      subscribeResult.textContent = payload.message || `Request failed (${response.status}).`;
      return;
    }
    subscribeResult.textContent = `Subscribed ${payload.email}. Confirm the SNS email before alerts arrive.`;
  } catch (error) {
    subscribeResult.textContent = `Could not reach the API (${error.message}).`;
  }
});

fetch("regions.json")
  .then((response) => {
    if (!response.ok) throw new Error(`regions.json returned ${response.status}`);
    return response.json();
  })
  .then((loaded) => {
    addRegions(loaded);
    return refresh();
  })
  .catch((error) => {
    statusEl.textContent = `Could not load regions.json (${error.message}). Serve this folder with python3 -m http.server.`;
  });
