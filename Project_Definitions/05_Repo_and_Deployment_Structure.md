# 仓库结构与部署结构

## 1. 仓库结构

```text
repo/
├── Project_Definitions/
├── deploy/
│   ├── compose.base.yml
│   ├── compose.control-plane.yml
│   ├── compose.worker.yml
│   ├── compose.worker.remote.yml
│   ├── compose.worker.remote.2gpu.yml
│   ├── compose.dev.yml
│   ├── docker/
│   ├── scripts/
│   │   └── render_remote_worker_compose.py
│   └── env/
├── models/
├── packages/
│   ├── common/
│   └── gvhmr_runner/
├── third_party/
│   └── GVHMR/
└── services/
    ├── api/
    ├── scheduler/
    └── worker/
```

## 2. 服务职责

### services/api

- FastAPI 接口
- 基础 Web 控制台
- 上传接收
- 查询与下载入口

### services/scheduler

- 轻量独立调度器
- 批次推进
- 优先级与 FIFO 分发

### services/worker

- GPU 任务执行
- 心跳上报
- 状态回写

### packages/common

- 枚举
- schema
- ID/时间工具
- 共享配置模型

### packages/gvhmr_runner

- 真正封装 GVHMR 执行过程
- 缓存键生成
- job 到 artifact 的执行规划
- 内置对 pinned GVHMR wrapper 的桥接入口

### third_party/GVHMR

- 上游 `GVHMR` 源码
- 以 git submodule 固定版本
- 当前固定 commit：`088caff492aa38c2d82cea363b78a3c65a83118f`
- 固定原因：上游当前没有可用 release tag，需要避免直接追踪 `main`

## 3. Compose 分层

### compose.base.yml

- 网络
- 公共 volume
- 公共命名约定

### compose.control-plane.yml

- api
- scheduler
- postgres
- redis
- minio
- migrate

### compose.worker.yml

- worker
- GPU 绑定
- 模型卷
- scratch 卷
- healthcheck
- restart policy

### compose.worker.remote.yml

- 远端单 worker 节点
- 不依赖本地 compose network
- 直接访问控制平面机器的 `Postgres/Redis/MinIO`
- 使用显式 host scratch 路径

### compose.worker.remote.2gpu.yml

- 远端 2 GPU worker 节点
- 一卡一 worker 容器
- 同一 `node_name`，不同 `gpu_slot`
- 独立 host scratch 路径
- 当前保留为兼容模板

### render_remote_worker_compose.py

- 推荐的远端部署入口
- 根据 `WORKER_GPU_IDS` 自动生成“任意 GPU 数量、一卡一 worker”的 compose 文件
- 输出到 `deploy/.generated/compose.worker.remote.generated.yml`
- 允许远端机器用同一套 env 模板覆盖 1 卡、2 卡、4 卡等场景
- 当前明确不支持同一物理 GPU 上配置多个 worker

### compose.dev.yml

- 源码挂载
- reload
- 开发环境覆盖配置

## 4. 环境变量边界

### 命名约定

- `deploy/env/*.example.env`：仓库内模板
- `deploy/env/*.env`：本机/目标机实际运行配置
- 通过 `make env-init` 从模板生成本地运行配置

### 控制平面

- `POSTGRES_DSN`
- `REDIS_URL`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

### Worker

- `WORKER_GPU_IDS`
- `WORKER_NODE_NAME`
- `WORKER_TORCH_CUDA_ARCH_LIST`
- `MODEL_ROOT`
- `WORKER_SCRATCH_ROOT`
- `GPU{N}_VISIBLE_DEVICE`（可选覆盖）
- `GPU{N}_SCRATCH_HOST_PATH`（可选覆盖）
- `WORKER_GPU_SLOT` / `WORKER_VISIBLE_DEVICE` / `WORKER_SCRATCH_HOST_PATH`（兼容单 worker 旧变量）
- `HEALTHCHECK_FILE`
- `HEALTHCHECK_MAX_AGE_SECONDS`
- `SCRATCH_MIN_FREE_BYTES`
- `SCRATCH_CLEANUP_INTERVAL_SECONDS`
- `SCRATCH_SUCCESS_TTL_SECONDS`
- `SCRATCH_FAILED_TTL_SECONDS`
- `SCRATCH_ORPHAN_TTL_SECONDS`
- `INFRA_RETRY_DELAY_SECONDS`
- `UPSTREAM_GVHMR_REF`
- `RUNNER_ENTRY_MODULE`
- `CLOCK_SKEW_WARN_SECONDS`
- `CLOCK_SKEW_FAIL_SECONDS`
- `IDENTITY_STALE_AFTER_SECONDS`

### 宿主机端口覆盖

- `HOST_API_PORT`
- `HOST_POSTGRES_PORT`
- `HOST_REDIS_PORT`
- `HOST_MINIO_PORT`
- `HOST_MINIO_CONSOLE_PORT`

## 5. 存储边界

### MinIO

- 输入视频
- 输出 artifact
- 执行日志

### 本地模型卷

- 仓库根目录 `models/`
- 各类 checkpoint
- `body_models` 作为 `models/` 的子目录

### 本地 scratch

- 临时视频
- 中间文件
- 局部 cache
- 远端多 worker 节点默认每个 worker 使用独立 host scratch 目录
- 如果 Docker data root 已经在本地 SSD，上单 worker 时不强制再单独准备一块盘
- worker 周期性清理陈旧 job scratch 目录，避免磁盘无限增长
- 推荐通过 `WORKER_SCRATCH_ROOT` 自动展开为 `.../gpu<gpu_slot>`

## 6. 迁移原则

- 不使用“API 容器本地结果目录”作为系统真源
- 不让 worker 依赖某个特定宿主机路径的最终结果
- 所有核心状态必须可在无共享文件系统场景下成立

## 7. 当前单机实现约束

- 当前 compose 默认宿主机端口使用高位端口，避免与旧仓库冲突
- worker 当前默认挂载仓库根目录 `models/` 到容器内 `inputs/checkpoints`
- `models/` 不纳入 git，用户需按文档自行下载和放置模型资产
- worker 当前直接从 CUDA 基础镜像和 `third_party/GVHMR` submodule 自行构建
- `use_dpvo=true` 对应的 DPVO CUDA 扩展在 worker 镜像 build 阶段编译
- 该编译当前通过 `WORKER_TORCH_CUDA_ARCH_LIST` 显式指定目标 GPU 架构，默认值为 `7.5;8.0;8.6;8.9`
- worker 启动需等待 `migrate` 完成，避免在表尚未创建时抢跑
- worker 启动前必须通过 `CUDA / models / scratch / Postgres / Redis / MinIO` preflight
- worker 失败时会尽量回传 `runner.log`，便于定位上游或运行时错误
- 当前自动 retry 只对 `infra_transient` 生效，默认回退 `30s`、最大 `1` 次
- `deploy/env/*.env` 不纳入 git，需通过模板初始化

## 8. 多机 Worker 约定

- 远端 worker 通过部署时 env 自我声明 `worker_id / node_name / gpu_slot`
- 统一命名规则：
  - `node_name = <机器名>`
  - `worker_id = <node_name>-gpu<gpu_slot>`
- `gpu_slot` 对应宿主机 `nvidia-smi` 序号
- 推荐通过 `WORKER_GPU_IDS=0,1,2,...` 生成整组 worker
- 每个 `gpu_slot` 只允许一个在线 worker
- 启动时会校验：
  - `worker_id` 未被其他在线 worker 占用
  - `node_name + gpu_slot` 未被其他在线 worker 占用
- 远端 worker 依赖宿主机时间同步；worker 启动时会检测与 Postgres 的时钟漂移
- `scheduled` 未被 claim 的 job 会在超时后回收到 `queued`
- `worker heartbeat timeout` 会把当前 job 归类为 `infra_transient`，在未超过重试次数时自动转回 `queued`
- 远端 worker 机器需要放通到控制平面机器的：
  - Postgres
  - Redis
  - MinIO API
