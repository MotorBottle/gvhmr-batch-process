# GVHMR Batch Process PRD

## 1. 产品定位

本产品是面向内网团队的 `GVHMR` 批量处理与集群执行平台，不再是单机同步 demo。产品的价值在于把“上传视频 -> 处理 -> 查询 -> 下载结果”升级为“提交任务/批次 -> 系统调度 -> 分布式执行 -> 平台化管理产物”。

## 2. 核心用户故事

### 2.1 单视频异步处理

作为用户，我希望上传一个视频并创建一个 job，然后异步查看其执行状态和结果，而不是阻塞等待。

### 2.2 批处理

作为用户，我希望一次提交多个视频，形成一个 batch，由平台自动排队并发执行。

### 2.3 单机多卡

作为运维/研发，我希望一台机器上的多个 GPU 都能被利用，每张 GPU 各跑一个 worker。

### 2.4 多机扩展

作为运维/研发，我希望把更多 GPU 机器接入系统，而不需要改 API 或前端逻辑。

### 2.5 可交付结果

作为用户，我希望处理完成后能稳定获得 `hmr4d_results.pt`、渲染视频、日志和 ZIP。

## 3. 功能需求

### 3.1 上传管理

- 支持上传单个视频文件
- 平台记录文件名、大小、类型、哈希、存储位置
- 上传完成后返回 `upload_id`

### 3.2 Job 管理

- 根据 `upload_id` 创建单个 job
- 可指定参数：
  - `static_camera`
  - `video_render`
  - `video_type`
  - `f_mm`
  - `priority`
- 可查询 job 当前状态
- 可取消尚未完成的 job

### 3.3 Batch 管理

- 一次提交多个 `upload_id` 形成 batch
- batch 自动生成多个 job
- 可查看 batch 状态统计：
  - 总数
  - queued
  - scheduled
  - running
  - succeeded
  - failed
  - canceled

### 3.4 Artifact 管理

- 平台统一记录 artifact 元数据
- 支持下载单个 artifact
- 支持后续扩展批量打包下载

### 3.5 Worker 管理

- 平台记录 worker 心跳
- 平台可查看 worker 所属节点、GPU 槽位、最近心跳时间、状态

### 3.6 调度

- Scheduler 按 `priority + FIFO` 选择可执行 job
- 同一 worker 同时只接一个 job
- 同一 GPU 不允许并发跑多个 job
- worker 失联后，job 可被标记失败或进入重试

## 4. 非功能需求

- API 具备清晰、稳定、可文档化的契约
- 系统分层明确，可替换本地开发实现为真实 Postgres/MinIO/Redis 后端
- 对象存储为所有输入输出真源
- Postgres 为元数据真源
- Redis 仅承担消息和调度通道角色

## 5. 第一阶段不做

- 用户系统与角色权限
- 项目空间与资源配额
- 跨租户隔离
- K8s 部署
- 自动扩缩容
- 复杂 SLA 调度器

## 6. 第一阶段交付判定

- API 可创建 upload/job/batch，并查询状态
- 基础 Web 能完成上传、创建 job、创建 batch、查询状态
- compose 可以分为控制平面与 worker 平面
- 仓库定义文件足够详细，可直接指导后续实现

