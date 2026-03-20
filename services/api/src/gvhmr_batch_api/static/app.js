const output = document.getElementById("output");

function render(data) {
  output.textContent = JSON.stringify(data, null, 2);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({ error: "Non-JSON response" }));
  if (!response.ok) {
    throw new Error(JSON.stringify(data, null, 2));
  }
  return data;
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

document.getElementById("jobForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    upload_id: document.getElementById("jobUploadId").value.trim(),
    static_camera: document.getElementById("jobStaticCamera").value === "true",
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
      static_camera: true,
      video_render: false,
      video_type: "none",
      f_mm: null,
      priority: "normal",
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

