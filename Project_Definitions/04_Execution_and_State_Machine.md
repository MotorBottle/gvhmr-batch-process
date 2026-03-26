# 执行模型与状态机

## 1. Job 状态机

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> scheduled
    queued --> canceled
    scheduled --> queued: claim timeout / auto retry
    scheduled --> running
    scheduled --> failed
    scheduled --> canceled
    running --> queued: auto retry
    running --> succeeded
    running --> failed
    running --> canceled
    failed --> queued: manual retry
```

### 状态含义

- `queued`：已创建，等待调度
- `scheduled`：已分配 worker，等待真正开始
- `running`：worker 已占用 GPU 开始执行
- `succeeded`：执行成功，artifact 已入存储
- `failed`：执行失败
- `canceled`：被用户取消或系统终止

## 2. Batch 状态机

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> queued
    queued --> running
    running --> succeeded
    running --> partial_failed
    running --> failed
    queued --> canceled
    running --> canceled
```

### Batch 判定规则

- 全部 job `queued/scheduled` 时：`queued`
- 存在 `running` 时：`running`
- 全部 `succeeded`：`succeeded`
- 全部失败或取消：`failed`
- 既有成功又有失败：`partial_failed`
- 用户整批取消：`canceled`

## 3. Worker 状态模型

- `idle`：空闲，可接新 job
- `busy`：正在执行 job
- `offline`：心跳超时

## 4. 调度规则

第一阶段固定规则：

- 先按 `priority` 排序
- 同优先级内按 `created_at` FIFO
- 只给 `idle` worker 分配 job
- 同一 worker 同时只能处理一个 job
- 同一 GPU 不允许多个并发 job

## 5. 重试规则

- `scheduled` job 如果在 claim timeout 内未被真正 `running`，会回收到 `queued`
- 当前自动 retry 只针对 `infra_transient`：
  - `CUDA runtime is unavailable`
  - `CUDA initialization failed`
  - `worker heartbeat timed out`
- 自动 retry 默认最多 `1` 次，默认回退延迟 `30s`
- `claim timeout` 回收不计入 `retry_count`
- `input invalid / algorithm failure / infra permanent / canceled` 不自动 retry
- 终态 `failed` 后仍可由后续显式接口或脚本做手动 retry

## 6. 取消规则

- `queued` job 可直接取消
- `scheduled` job 可取消并释放分配
- `running` job 标记为取消请求，由 worker 响应后进入 `canceled`

## 7. 缓存规则

### 核心推理缓存键

`video_sha256 + static_camera + use_dpvo(仅动态相机时) + f_mm + upstream_version`

### 渲染缓存键

`核心推理缓存键 + video_render + video_type`

### 缓存作用

- 相同视频、相同核心参数复用 preprocess 与主推理结果
- 仅更改视频渲染参数时，不重复跑核心 GVHMR 推理
- 动态相机下，`SimpleVO` 与 `DPVO` 使用不同核心缓存键，避免错误复用

## 8. 交付流程

1. 用户上传视频
2. API 创建 upload 记录并写入存储
3. API 创建 job/batch 元数据
4. Scheduler 从队列和数据库选择待执行 job
5. Scheduler 为 job 选择 worker
6. Worker 下载输入并执行 `gvhmr_runner`
7. Worker 上传 artifact 到 MinIO
8. Worker 更新 job 成功或失败状态
9. API 暴露查询与下载接口

## 9. Worker 可靠性约束

- worker 启动前必须完成 preflight：
  - CUDA 可用
  - 模型目录完整
  - scratch 可写且剩余空间高于阈值
  - Postgres / Redis / MinIO 可连通
- worker 运行时通过容器 healthcheck 保活；healthcheck 失败时由容器编排层重启
- 基础设施级错误不允许 worker 静默留在集群中继续接单
- 失败 job 应尽量保留 `runner.log` 作为 artifact
- scratch 目录由 worker 周期性清理，不保留无限增长的历史临时文件
