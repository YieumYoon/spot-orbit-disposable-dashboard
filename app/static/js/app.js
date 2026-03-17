const APP = window.SPOT_ORBIT_DASHBOARD;

const state = {
  range: APP.defaultRange,
  charts: {},
  clientWarnings: [],
  timerId: null,
};

const chartPalette = {
  runs: "#56c7ff",
  captures: "#79d498",
  events: "#f4b942",
  status: ["#79d498", "#ff7a59", "#ff9f68", "#f4b942", "#56c7ff", "#c48eff", "#96a6b5"],
};

const bucketDayFormatter = new Intl.DateTimeFormat("en-US", {
  day: "numeric",
  timeZone: APP.timezone,
});

const bucketMonthFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  timeZone: APP.timezone,
});

const bucketMonthKeyFormatter = new Intl.DateTimeFormat("en-US", {
  month: "numeric",
  year: "numeric",
  timeZone: APP.timezone,
});

const bucketTooltipFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeZone: APP.timezone,
});

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

function addClientWarning(message) {
  if (!state.clientWarnings.includes(message)) {
    state.clientWarnings.push(message);
  }
}

function rangePeriodLabel(rangeKey) {
  if (rangeKey === "24h") return "last 24 hours";
  if (rangeKey === "7d") return "last 7 days";
  if (rangeKey === "30d") return "last 30 days";
  return "selected period";
}

function rangeBucketLabel(rangeKey) {
  return rangeKey === "24h" ? "hour" : "day";
}

function mergedWarnings(warnings) {
  return [...new Set([...(warnings || []), ...state.clientWarnings])];
}

function statusChipClass(status) {
  const normalized = status || "unknown";
  if (normalized === "running") return "status-chip status-chip--active";
  if (normalized === "success") return "status-chip status-chip--success";
  if (normalized === "paused" || normalized === "stopped") return "status-chip status-chip--warning";
  if (normalized === "failure" || normalized === "error") return "status-chip status-chip--error";
  return "status-chip status-chip--unknown";
}

function titleCaseLabel(value) {
  if (!value) {
    return "Unknown";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function createOrUpdateChart(key, elementId, config) {
  if (state.charts[key]) {
    state.charts[key].destroy();
  }
  const context = document.getElementById(elementId).getContext("2d");
  state.charts[key] = new window.Chart(context, config);
}

function bucketDate(bucket) {
  if (!bucket?.bucketStart) {
    return null;
  }

  const date = new Date(bucket.bucketStart);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date;
}

function bucketMonthKey(bucket) {
  const date = bucketDate(bucket);
  if (!date) {
    return "";
  }
  return bucketMonthKeyFormatter.format(date);
}

function timeSeriesLabels(buckets, rangeKey) {
  if (rangeKey !== "30d") {
    return buckets.map((bucket) => bucket.label);
  }

  return buckets.map((bucket, index) => {
    const date = bucketDate(bucket);
    if (!date) {
      return bucket.label;
    }

    const dayLabel = bucketDayFormatter.format(date);
    const previousBucket = buckets[index - 1];
    const startsNewMonth = index === 0 || bucketMonthKey(previousBucket) !== bucketMonthKey(bucket);
    if (startsNewMonth) {
      return [bucketMonthFormatter.format(date), dayLabel];
    }

    return ["", dayLabel];
  });
}

function timeSeriesTooltipTitle(buckets, dataIndex) {
  const bucket = buckets[dataIndex];
  const date = bucketDate(bucket);
  if (!date) {
    return bucket?.label || "";
  }
  return bucketTooltipFormatter.format(date);
}

function timeSeriesChartOptions(buckets, rangeKey) {
  const isThirtyDayRange = rangeKey === "30d";

  return {
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: isThirtyDayRange ? {
        callbacks: {
          title(items) {
            const item = items[0];
            return timeSeriesTooltipTitle(buckets, item?.dataIndex ?? 0);
          },
        },
      } : undefined,
    },
    scales: {
      x: {
        ticks: {
          autoSkip: !isThirtyDayRange,
          maxRotation: 0,
          minRotation: 0,
          padding: isThirtyDayRange ? 8 : 0,
        },
      },
      y: {
        beginAtZero: true,
        ticks: {
          precision: 0,
        },
      },
    },
  };
}

function renderTimeSeriesChart(key, elementId, buckets, color, rangeKey) {
  createOrUpdateChart(key, elementId, {
    type: "bar",
    data: {
      labels: timeSeriesLabels(buckets, rangeKey),
      datasets: [{
        data: buckets.map((bucket) => bucket.count),
        backgroundColor: color,
      }],
    },
    options: timeSeriesChartOptions(buckets, rangeKey),
  });
}

function renderWarnings(warnings) {
  const strip = document.getElementById("warning-strip");
  const combined = mergedWarnings(warnings);
  if (!combined.length) {
    strip.classList.add("is-hidden");
    strip.textContent = "";
    return;
  }
  strip.classList.remove("is-hidden");
  strip.textContent = combined.join(" ");
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

function renderNarrative(rangeKey) {
  const periodLabel = rangePeriodLabel(rangeKey);
  const bucketLabel = rangeBucketLabel(rangeKey);

  document.getElementById("card-last-activity-detail").textContent = `Most recent run, activity update, or capture recorded in the ${periodLabel}.`;
  document.getElementById("card-runs-detail").textContent = `Runs that began in the ${periodLabel}.`;
  document.getElementById("card-successful-runs-detail").textContent = `Runs in the ${periodLabel} that finished with a final status of Success.`;
  document.getElementById("card-captures-detail").textContent = `Captures recorded in the ${periodLabel}.`;
  document.getElementById("card-open-anomalies-detail").textContent = `Current open issue count in Orbit. Some issues may have been reported before the ${periodLabel}.`;

  document.getElementById("runs-chart-detail").textContent = `Runs that began each ${bucketLabel} in the ${periodLabel}.`;
  document.getElementById("status-chart-detail").textContent = `Status breakdown for runs that began in the ${periodLabel}.`;
  document.getElementById("captures-chart-detail").textContent = `Captures recorded each ${bucketLabel} in the ${periodLabel}.`;
  document.getElementById("events-chart-detail").textContent = `Action-level Orbit activity recorded each ${bucketLabel} in the ${periodLabel}.`;
  document.getElementById("anomaly-panel-detail").textContent = `Open shows the current issue backlog. New and closed show issue activity in the ${periodLabel}.`;
  document.getElementById("runs-panel-detail").textContent = `Most recent runs that began in the ${periodLabel}. Actions shows Orbit's recorded action count for each run.`;
  document.getElementById("events-panel-detail").textContent = `Most recent action-level Orbit activity in the ${periodLabel}, including event type and attached captures.`;
}

function renderCharts(trends, rangeKey) {
  if (typeof window.Chart !== "function") {
    addClientWarning("Charts are unavailable because the dashboard could not load its local chart library.");
    return;
  }

  renderTimeSeriesChart("runs", "runs-chart", trends.runsByBucket, chartPalette.runs, rangeKey);

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

  renderTimeSeriesChart("captures", "captures-chart", trends.capturesByBucket, chartPalette.captures, rangeKey);
  renderTimeSeriesChart("events", "events-chart", trends.eventsByBucket, chartPalette.events, rangeKey);
}

function renderRuns(rows, rangeKey) {
  const body = document.getElementById("runs-table-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td class="empty-state" colspan="5">No runs started in the ${rangePeriodLabel(rangeKey)}.</td></tr>`;
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

function renderEvents(events, rangeKey) {
  const shell = document.getElementById("events-feed");
  if (!events.length) {
    shell.innerHTML = `<div class="empty-state">No run activity was recorded in the ${rangePeriodLabel(rangeKey)}.</div>`;
    return;
  }
  shell.innerHTML = events.map((event) => `
    <article class="feed-card">
      <div class="feed-card__time">${formatTimestamp(event.time)}</div>
      <h3 class="feed-card__title">${event.actionName || "Unnamed action"}</h3>
      <div class="feed-card__meta">
        <div>${event.missionName || "Unnamed mission"}</div>
        <div>Type: ${event.eventType || "Not provided"}</div>
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
    body.innerHTML = `<tr><td class="empty-state" colspan="4">No issues are available in the current Orbit snapshot.</td></tr>`;
    return;
  }
  body.innerHTML = snapshot.recent.map((item) => `
    <tr>
      <td>${item.title}</td>
      <td><span class="${statusChipClass(item.status === "open" ? "warning" : "success")}">${titleCaseLabel(item.status)}</span></td>
      <td>${item.severity ?? "—"}</td>
      <td>${formatTimestamp(item.createdAt || item.time)}</td>
    </tr>
  `).join("");
}

function renderDashboard(payload) {
  renderNarrative(payload.range);
  renderWarnings(payload.warnings);
  renderSummary(payload.summary);
  renderCharts(payload.trends, payload.range);
  renderRuns(payload.recentRuns, payload.range);
  renderEvents(payload.recentEvents, payload.range);
  renderAnomalies(payload.anomalies);
  document.getElementById("last-refresh").textContent = formatTimestamp(payload.generatedAt);
}

async function loadDashboard() {
  setStateMessage("Refreshing dashboard…");
  try {
    const response = await fetch(`${APP.apiUrl}?range=${encodeURIComponent(state.range)}`);
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const payload = await response.json();
    renderDashboard(payload);
    setStateMessage(`Showing activity from the ${rangePeriodLabel(state.range)}.`);
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
