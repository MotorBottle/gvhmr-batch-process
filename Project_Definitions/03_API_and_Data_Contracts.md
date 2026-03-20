# API 与数据契约

## 1. API 列表

### 上传

- `POST /uploads`

用途：

- 上传单个视频文件
- 返回 `upload_id`

### Job

- `POST /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `GET /jobs/{job_id}/artifacts`

### Batch

- `POST /batches`
- `GET /batches/{batch_id}`

### Artifact

- `GET /artifacts/{artifact_id}/download`

### Worker

- `GET /workers`

### Health

- `GET /health`

## 2. 核心数据类型

### Upload

字段：

- `id`
- `filename`
- `content_type`
- `size_bytes`
- `sha256`
- `storage_key`
- `created_at`

### Job

字段：

- `id`
- `batch_id`
- `upload_id`
- `status`
- `priority`
- `static_camera`
- `video_render`
- `video_type`
- `f_mm`
- `assigned_worker_id`
- `assigned_gpu_slot`
- `artifact_count`
- `error_message`
- `created_at`
- `updated_at`

### Batch

字段：

- `id`
- `name`
- `status`
- `job_ids`
- `counts`
- `created_at`
- `updated_at`

### Artifact

字段：

- `id`
- `job_id`
- `kind`
- `filename`
- `storage_key`
- `created_at`

### WorkerHeartbeat

字段：

- `id`
- `node_name`
- `gpu_slot`
- `status`
- `last_heartbeat_at`
- `running_job_id`

### JobAssignment

字段：

- `job_id`
- `worker_id`
- `assigned_at`

## 3. Job 请求契约

```json
{
  "upload_id": "upl_xxx",
  "static_camera": true,
  "video_render": false,
  "video_type": "none",
  "f_mm": null,
  "priority": "normal"
}
```

## 4. Batch 请求契约

```json
{
  "name": "batch-20260320",
  "items": [
    {
      "upload_id": "upl_a",
      "static_camera": true,
      "video_render": false,
      "video_type": "none",
      "f_mm": null,
      "priority": "normal"
    },
    {
      "upload_id": "upl_b",
      "static_camera": false,
      "video_render": true,
      "video_type": "all",
      "f_mm": 24,
      "priority": "high"
    }
  ]
}
```

## 5. 状态枚举

### JobStatus

- `queued`
- `scheduled`
- `running`
- `succeeded`
- `failed`
- `canceled`

### BatchStatus

- `draft`
- `queued`
- `running`
- `partial_failed`
- `succeeded`
- `failed`
- `canceled`

### WorkerStatus

- `idle`
- `busy`
- `offline`

## 6. ArtifactKind

- `input_video`
- `preprocess`
- `hmr4d_results`
- `render_video`
- `joints_json`
- `log`
- `archive`

## 7. API 契约约束

- 所有响应必须带 `id` 和明确状态字段
- 所有时间字段使用 UTC ISO8601
- 所有下载能力通过 artifact 层暴露
- batch 只汇总 job，不直接持有大对象

