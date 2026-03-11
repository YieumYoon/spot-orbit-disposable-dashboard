const APP = window.SPOT_ORBIT_DASHBOARD;

const state = {
  range: APP.defaultRange,
  charts: {},
  timerId: null,
};

const chartPalette = {
  runs: "#56c7ff",
  captures: "#79d498",
  events: "#f4b942",
  status: ["#79d498", "#ff7a59", "#ff9f68", "#f4b942", "#56c7ff", "#c48eff", "#96a6b5"],
};

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: APP.timezone,
  }).format(new Date(timestamp));
}

function setStateMessage(message, isError = false) {
  const element = document.getElementById("load-state");
  element.textContent = message;
  element.style.color = isError ? "#ff7a59" : "";
}

function statusChipClass(status) {
  const normalized = status || "unknown";
  if (normalized === "running") return "status-chip status-chip--active";
  if (normalized === "success") return "status-chip status-chip--success";
  if (normalized === "paused" || normalized === "stopped") return "status-chip status-chip--warning";
  if (normalized === "failure" || normalized === "error") return "status-chip status-chip--error";
  return "status-chip status-chip--unknown";
}

function createOrUpdateChart(key, elementId, config) {
  if (state.charts[key]) {
    state.charts[key].destroy();
  }
  const context = document.getElementById(elementId).getContext("2d");
  state.charts[key] = new window.Chart(context, config);
}

function renderWarnings(warnings) {
  const strip = document.getElementById("warning-strip");
  if (!warnings || warnings.length === 0) {
    strip.classList.add("is-hidden");
    strip.textContent = "";
    return;
  }
  strip.classList.remove("is-hidden");
  strip.textContent = warnings.join(" ");
}

function renderSummary(summary) {
  document.getElementById("card-robot-status").textContent = summary.robotStatus.label;
  document.getElementById("card-robot-detail").textContent = summary.robotStatus.detail;
  document.getElementById("card-last-activity").textContent = formatTimestamp(summary.lastActivityAt);
  document.getElementById("card-runs").textContent = summary.runs;
  document.getElementById("card-successful-runs").textContent = summary.successfulRuns;
  document.getElementById("card-captures").textContent = summary.dataCaptures;
  document.getElementById("card-open-anomalies").textContent = summary.openAnomalies;
}

function renderCharts(trends) {
  createOrUpdateChart("runs", "runs-chart", {
    type: "bar",
    data: {
      labels: trends.runsByBucket.map((item) => item.label),
      datasets: [{ data: trends.runsByBucket.map((item) => item.count), backgroundColor: chartPalette.runs }],
    },
  });

  const statusMix = trends.missionStatusMix.filter((item) => item.count > 0);
  createOrUpdateChart("status", "status-chart", {
    type: "doughnut",
    data: {
      labels: statusMix.map((item) => item.label),
      datasets: [{
        data: statusMix.map((item) => item.count),
        backgroundColor: chartPalette.status,
      }],
    },
  });

  createOrUpdateChart("captures", "captures-chart", {
    type: "bar",
    data: {
      labels: trends.capturesByBucket.map((item) => item.label),
      datasets: [{ data: trends.capturesByBucket.map((item) => item.count), backgroundColor: chartPalette.captures }],
    },
  });

  createOrUpdateChart("events", "events-chart", {
    type: "bar",
    data: {
      labels: trends.eventsByBucket.map((item) => item.label),
      datasets: [{ data: trends.eventsByBucket.map((item) => item.count), backgroundColor: chartPalette.events }],
    },
  });
}

function renderRuns(rows) {
  const body = document.getElementById("runs-table-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td class="empty-state" colspan="5">No runs in the selected window.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.missionName}</td>
      <td><span class="${statusChipClass(row.status)}">${row.statusLabel}</span></td>
      <td>${formatTimestamp(row.startTime)}</td>
      <td>${formatTimestamp(row.endTime)}</td>
      <td>${row.actionCount}</td>
    </tr>
  `).join("");
}

function renderEvents(events) {
  const shell = document.getElementById("events-feed");
  if (!events.length) {
    shell.innerHTML = `<div class="empty-state">No recent events for this range.</div>`;
    return;
  }
  shell.innerHTML = events.map((event) => `
    <article class="feed-card">
      <div class="feed-card__time">${formatTimestamp(event.time)}</div>
      <h3 class="feed-card__title">${event.actionName || "Unnamed action"}</h3>
      <div class="feed-card__meta">
        <div>${event.missionName || "Unknown mission"}</div>
        <div>Type: ${event.eventType || "n/a"}</div>
        <div>Captures: ${event.captureCount}</div>
      </div>
    </article>
  `).join("");
}

function renderAnomalies(snapshot) {
  document.getElementById("anomaly-open").textContent = snapshot.openCount;
  document.getElementById("anomaly-closed").textContent = snapshot.closedInRange;
  document.getElementById("anomaly-new").textContent = snapshot.newInRange;

  const body = document.getElementById("anomaly-table-body");
  if (!snapshot.recent.length) {
    body.innerHTML = `<tr><td class="empty-state" colspan="4">No anomalies available.</td></tr>`;
    return;
  }
  body.innerHTML = snapshot.recent.map((item) => `
    <tr>
      <td>${item.title}</td>
      <td><span class="${statusChipClass(item.status === "open" ? "warning" : "success")}">${item.status}</span></td>
      <td>${item.severity ?? "—"}</td>
      <td>${formatTimestamp(item.createdAt || item.time)}</td>
    </tr>
  `).join("");
}

function renderDashboard(payload) {
  renderWarnings(payload.warnings);
  renderSummary(payload.summary);
  renderCharts(payload.trends);
  renderRuns(payload.recentRuns);
  renderEvents(payload.recentEvents);
  renderAnomalies(payload.anomalies);
  document.getElementById("last-refresh").textContent = formatTimestamp(payload.generatedAt);
}

async function loadDashboard() {
  setStateMessage("Refreshing live Orbit summary…");
  try {
    const response = await fetch(`${APP.apiUrl}?range=${encodeURIComponent(state.range)}`);
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const payload = await response.json();
    renderDashboard(payload);
    setStateMessage(`Range ${state.range} loaded.`);
  } catch (error) {
    console.error(error);
    setStateMessage("Unable to load dashboard data.", true);
  }
}

function bindRangeButtons() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextRange = button.dataset.range;
      if (!nextRange || nextRange === state.range) {
        return;
      }
      state.range = nextRange;
      document.querySelectorAll("[data-range]").forEach((pill) => {
        pill.classList.toggle("is-active", pill.dataset.range === nextRange);
      });
      loadDashboard();
    });
  });
}

async function loadHealth() {
  try {
    const response = await fetch("/healthz");
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const protocol = window.location.protocol || "http:";
    const host = window.location.hostname || payload.bindHost;
    const port = payload.port || 8080;
    document.getElementById("website-link").textContent = `${protocol}//${host}:${port}/`;
  } catch (error) {
    console.error(error);
  }
}

function startRefreshLoop() {
  if (state.timerId) {
    window.clearInterval(state.timerId);
  }
  state.timerId = window.setInterval(loadDashboard, APP.refreshSeconds * 1000);
}

window.addEventListener("DOMContentLoaded", async () => {
  bindRangeButtons();
  await loadHealth();
  await loadDashboard();
  startRefreshLoop();
});
