const output = document.getElementById("output");
const dashboardServices = document.getElementById("dashboardServices");
const dashboardWorkers = document.getElementById("dashboardWorkers");
const dashboardJobs = document.getElementById("dashboardJobs");
const dashboardBatches = document.getElementById("dashboardBatches");
const dashboardUpdatedAt = document.getElementById("dashboardUpdatedAt");
const dashboardRefreshButton = document.getElementById("dashboardRefreshButton");

const DASHBOARD_REFRESH_MS = 5000;

function render(data) {
  output.textContent = JSON.stringify(data, null, 2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStatusRows(element, rows, emptyLabel) {
  if (!rows.length) {
    element.innerHTML = `<div class="status-row"><span class="status-name">${escapeHtml(emptyLabel)}</span><span class="status-value">-</span></div>`;
    return;
  }

  element.innerHTML = rows.map((row) => `
    <div class="status-row">
      <span class="status-name">${escapeHtml(row.name)}</span>
      <span class="status-value ${escapeHtml(row.statusClass || "")}">${escapeHtml(row.value)}</span>
    </div>
  `).join("");
}

function toLocalTime(isoString) {
  if (!isoString) {
    return "-";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return isoString;
  }
  return date.toLocaleString();
}

function renderDashboard(data) {
  const serviceRows = Object.entries(data.health.services || {}).map(([name, status]) => ({
    name,
    value: status,
    statusClass: String(status).toLowerCase(),
  }));
  serviceRows.unshift({
    name: "app",
    value: data.health.status,
    statusClass: String(data.health.status).toLowerCase(),
  });
  renderStatusRows(dashboardServices, serviceRows, "暂无组件状态");

  const workerRows = (data.workers || []).map((worker) => ({
    name: `${worker.node_name} / gpu${worker.gpu_slot}`,
    value: worker.running_job_id ? `${worker.status} · ${worker.running_job_id}` : `${worker.status} · idle`,
    statusClass: String(worker.status).toLowerCase(),
  }));
  renderStatusRows(dashboardWorkers, workerRows, "暂无 worker");

  const jobRows = (data.active_jobs || []).map((job) => ({
    name: `${job.id} · ${job.upload_filename || job.upload_id}`,
    value: `${job.status} · ${job.priority}${job.assigned_worker_id ? ` · ${job.assigned_worker_id}` : ""}`,
    statusClass: String(job.status).toLowerCase(),
  }));
  renderStatusRows(dashboardJobs, jobRows, "当前无活动任务");

  const batchRows = (data.active_batches || []).map((batch) => ({
    name: `${batch.id} · ${batch.name}`,
    value: `${batch.status} · total ${batch.counts.total_jobs} · running ${batch.counts.running} · queued ${batch.counts.queued}`,
    statusClass: String(batch.status).toLowerCase(),
  }));
  renderStatusRows(dashboardBatches, batchRows, "当前无活动 batch");

  dashboardUpdatedAt.textContent = `刷新于 ${toLocalTime(data.refreshed_at)}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({ error: "Non-JSON response" }));
  if (!response.ok) {
    throw new Error(JSON.stringify(data, null, 2));
  }
  return data;
}

async function refreshDashboard() {
  try {
    const data = await fetchJson("/dashboard/overview");
    renderDashboard(data);
  } catch (error) {
    dashboardUpdatedAt.textContent = "刷新失败";
    renderStatusRows(dashboardServices, [{ name: "dashboard", value: error.message, statusClass: "failed" }], "dashboard error");
    renderStatusRows(dashboardWorkers, [], "暂无 worker");
    renderStatusRows(dashboardJobs, [], "当前无活动任务");
    renderStatusRows(dashboardBatches, [], "当前无活动 batch");
  }
}

document.getElementById("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("uploadFile").files[0];
  if (!file) {
    render({ error: "请选择文件。" });
    return;
  }

  const formData = new FormData();
  formData.append("video", file);

  try {
    const data = await fetchJson("/uploads", {
      method: "POST",
      body: formData,
    });
    document.getElementById("jobUploadId").value = data.id;
    render(data);
  } catch (error) {
    render({ error: error.message });
  }
});

dashboardRefreshButton.addEventListener("click", async () => {
  await refreshDashboard();
});

void refreshDashboard();
window.setInterval(() => {
  void refreshDashboard();
}, DASHBOARD_REFRESH_MS);

document.getElementById("jobForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    upload_id: document.getElementById("jobUploadId").value.trim(),
    static_camera: document.getElementById("jobStaticCamera").value === "true",
    use_dpvo: document.getElementById("jobUseDpvo").value === "true",
    video_render: document.getElementById("jobVideoRender").value === "true",
    video_type: document.getElementById("jobVideoType").value.trim() || "none",
    f_mm: document.getElementById("jobFmm").value ? Number(document.getElementById("jobFmm").value) : null,
    priority: document.getElementById("jobPriority").value,
  };

  try {
    const data = await fetchJson("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("lookupJobId").value = data.id;
    render(data);
  } catch (error) {
    render({ error: error.message });
  }
});

document.getElementById("batchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const uploadIds = document.getElementById("batchUploadIds").value
    .split("\n")
    .map((value) => value.trim())
    .filter(Boolean);

  const payload = {
    name: document.getElementById("batchName").value.trim(),
    items: uploadIds.map((uploadId) => ({
      upload_id: uploadId,
      static_camera: document.getElementById("batchStaticCamera").value === "true",
      use_dpvo: document.getElementById("batchUseDpvo").value === "true",
      video_render: document.getElementById("batchVideoRender").value === "true",
      video_type: document.getElementById("batchVideoType").value.trim() || "none",
      f_mm: document.getElementById("batchFmm").value ? Number(document.getElementById("batchFmm").value) : null,
      priority: document.getElementById("batchPriority").value,
    })),
  };

  try {
    const data = await fetchJson("/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("lookupBatchId").value = data.id;
    render(data);
  } catch (error) {
    render({ error: error.message });
  }
});

document.getElementById("jobLookupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobId = document.getElementById("lookupJobId").value.trim();
  try {
    render(await fetchJson(`/jobs/${jobId}`));
  } catch (error) {
    render({ error: error.message });
  }
});

document.getElementById("batchLookupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const batchId = document.getElementById("lookupBatchId").value.trim();
  try {
    render(await fetchJson(`/batches/${batchId}`));
  } catch (error) {
    render({ error: error.message });
  }
});

document.getElementById("healthForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    render(await fetchJson("/health"));
  } catch (error) {
    render({ error: error.message });
  }
});
