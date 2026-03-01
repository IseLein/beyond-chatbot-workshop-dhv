const feedEl = document.getElementById("feed");
const statusEl = document.getElementById("status-json");
const eventsEl = document.getElementById("events");
const snapshotsEl = document.getElementById("snapshots");
const phoneDetectedEl = document.getElementById("phone-detected");
const confidenceEl = document.getElementById("confidence");
const actionEl = document.getElementById("action");
const reasonEl = document.getElementById("reason");
const observationEl = document.getElementById("observation");
const feedHealthEl = document.getElementById("feed-health");
const latencyEl = document.getElementById("latency");

const modelEl = document.getElementById("model");
const intervalEl = document.getElementById("analysis-interval");
const thresholdEl = document.getElementById("confidence-threshold");
const cooldownEl = document.getElementById("cooldown-seconds");

const startBtn = document.getElementById("start");
const stopBtn = document.getElementById("stop");
const saveConfigBtn = document.getElementById("save-config");
const applyModelBtn = document.getElementById("apply-model");
let framePollTimer = null;

async function requestJSON(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatConfidence(value) {
  const num = toNumber(value);
  if (num === null) return "-";
  return `${Math.round(num * 100)}%`;
}

function renderAnalysis(lastStatus) {
  const parsed = lastStatus && typeof lastStatus.parsed === "object" ? lastStatus.parsed : null;

  if (!parsed) {
    phoneDetectedEl.className = "pill pill-neutral";
    phoneDetectedEl.textContent = "Unknown";
    confidenceEl.textContent = "-";
    actionEl.textContent = "-";
    reasonEl.textContent = "-";
    observationEl.textContent = "No parsed analysis yet. Check Agent Status for raw output.";
    return;
  }

  const phoneDetected = parsed.phone_detected;
  if (phoneDetected === true) {
    phoneDetectedEl.className = "pill pill-positive";
    phoneDetectedEl.textContent = "Yes";
  } else if (phoneDetected === false) {
    phoneDetectedEl.className = "pill pill-negative";
    phoneDetectedEl.textContent = "No";
  } else {
    phoneDetectedEl.className = "pill pill-neutral";
    phoneDetectedEl.textContent = "Unknown";
  }

  confidenceEl.textContent = formatConfidence(parsed.confidence);
  actionEl.textContent = String(parsed.action || "none");
  reasonEl.textContent = String(parsed.reason || "-");
  observationEl.textContent = String(parsed.observation || "No observation provided.");
}

function renderEvents(items) {
  if (!items || items.length === 0) {
    eventsEl.innerHTML = "<p>No events yet.</p>";
    return;
  }

  const rows = items
    .slice()
    .reverse()
    .map((item) => {
      const body = JSON.stringify(item);
      return `<div class="event">${body}</div>`;
    });
  eventsEl.innerHTML = rows.join("");
}

function renderSnapshots(items) {
  if (!items || items.length === 0) {
    snapshotsEl.innerHTML = "<p>No snapshots yet.</p>";
    return;
  }

  const cards = items.map(
    (item) =>
      `<a class="snapshot-card" href="${item.url}" target="_blank" rel="noreferrer">
        <img src="${item.url}" alt="${item.name}" />
        <span>${item.name}</span>
      </a>`
  );

  snapshotsEl.innerHTML = cards.join("");
}

function startFramePolling() {
  if (framePollTimer !== null) return;
  const tick = () => {
    feedEl.src = `/frame.jpg?t=${Date.now()}`;
  };
  tick();
  framePollTimer = setInterval(tick, 300);
}

function stopFramePolling() {
  if (framePollTimer !== null) {
    clearInterval(framePollTimer);
    framePollTimer = null;
  }
  feedEl.src = "";
}

function renderStatus(status) {
  statusEl.textContent = JSON.stringify(status.last_status, null, 2);
  renderAnalysis(status.last_status || {});
  renderEvents(status.recent_events || []);
  renderSnapshots(status.recent_snapshots || []);

  if (status.running) {
    startFramePolling();
  } else {
    stopFramePolling();
  }

  if (!status.running) {
    feedHealthEl.textContent = "Feed: idle";
  } else if (!status.has_frame) {
    feedHealthEl.textContent = "Feed: waiting for first frame";
  } else {
    const frameCount = status.frames_captured ?? 0;
    const at = status.last_frame_at ? ` at ${status.last_frame_at}` : "";
    feedHealthEl.textContent = `Feed: receiving frames (${frameCount})${at}`;
  }

  const latency = toNumber(status.last_status && status.last_status.latency_ms);
  latencyEl.textContent = latency === null ? "Latency: -" : `Latency: ${latency}ms`;

  intervalEl.value = status.analysis_interval_ms;
  thresholdEl.value = status.confidence_threshold;
  cooldownEl.value = status.cooldown_seconds;
  modelEl.value = status.model;
}

async function refreshStatus() {
  try {
    const status = await requestJSON("/api/status");
    renderStatus(status);
  } catch (error) {
    statusEl.textContent = `Error: ${error.message}`;
  }
}

startBtn.addEventListener("click", async () => {
  try {
    const payload = await requestJSON("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelEl.value.trim() }),
    });
    renderStatus(payload.status);
  } catch (error) {
    statusEl.textContent = `Error: ${error.message}`;
  }
});

stopBtn.addEventListener("click", async () => {
  try {
    const payload = await requestJSON("/api/stop", { method: "POST" });
    renderStatus(payload.status);
  } catch (error) {
    statusEl.textContent = `Error: ${error.message}`;
  }
});

saveConfigBtn.addEventListener("click", async () => {
  try {
    const payload = await requestJSON("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis_interval_ms: Number(intervalEl.value),
        confidence_threshold: Number(thresholdEl.value),
        cooldown_seconds: Number(cooldownEl.value),
      }),
    });
    renderStatus(payload.status);
  } catch (error) {
    statusEl.textContent = `Error: ${error.message}`;
  }
});

applyModelBtn.addEventListener("click", async () => {
  try {
    const payload = await requestJSON("/api/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelEl.value.trim() }),
    });
    renderStatus(payload.status);
  } catch (error) {
    statusEl.textContent = `Error: ${error.message}`;
  }
});

feedEl.addEventListener("error", () => {
  if (!feedEl.src || !feedEl.src.includes("/frame.jpg")) return;
  setTimeout(() => {
    feedEl.src = `/frame.jpg?t=${Date.now()}`;
  }, 300);
});

refreshStatus();
setInterval(refreshStatus, 1500);
