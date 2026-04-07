# GVHMR Batch Process

面向 `GVHMR` 的新一代批处理与集群化处理框架。

当前仓库已经完成两部分工作：

- `Project_Definitions/`：产品与工程定义文件已固化，可直接作为后续实现依据
- Phase 2 单机单卡垂直切片：`Postgres + MinIO + API + Scheduler + Worker` 已经打通

## 仓库结构

```text
.
├── Makefile
├── Project_Definitions/
├── deploy/
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

## 当前定位

- 新标准架构，不兼容旧版同步 `/process`
- 第一阶段目标：异步 API、批处理、基础 Web 控制台
- 当前实现：本机 Docker Compose 单机单卡闭环
- 目标部署方式：Docker Compose 控制平面 + 分布式 GPU worker

## 当前已实现能力

- `POST /uploads`：文件写入 MinIO，元数据写入 Postgres
- `POST /jobs` / `GET /jobs/{id}` / `POST /jobs/{id}/cancel`
- `POST /batches` / `GET /batches/{id}`
- `GET /jobs/{id}/artifacts` / `GET /artifacts/{id}/download`
- `GET /workers` / `GET /health`
- Scheduler 已切到 `Postgres 真源 + Redis 消息通道` 分发模型
- Worker 已接入真实 GVHMR 执行链路，并写回真实 `hmr4d_results.pt` 与预处理产物
- Job / Batch 已支持显式选择 `use_dpvo`，用于动态相机时切换 `SimpleVO` 与 `DPVO`
- Worker 已补充可靠性增强：
  - 启动前 `CUDA / models / scratch / Postgres / Redis / MinIO` preflight
  - 运行时 `healthcheck + restart`
  - `scheduled` 未 claim 超时自动回收
  - 失败时尽量保留 `runner.log`
  - `CUDA unavailable / CUDA init failed / worker heartbeat timeout` 自动 retry 1 次
  - scratch 自动清理陈旧 job 目录
- 上游 `GVHMR` 以 git submodule 固定到 `088caff492aa38c2d82cea363b78a3c65a83118f`

## 本机启动

更完整的主节点部署步骤见：

- [deploy/README.host-deployment.md](deploy/README.host-deployment.md)

```bash
git submodule update --init --recursive
make env-init

docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  -f deploy/compose.worker.yml \
  up --build -d
```

默认宿主机端口：

- API: `18000`
- Postgres: `15432`
- Redis: `16379`
- MinIO API: `19000`
- MinIO Console: `19001`

这些端口都支持通过环境变量覆盖：

- `HOST_API_PORT`
- `HOST_POSTGRES_PORT`
- `HOST_REDIS_PORT`
- `HOST_MINIO_PORT`
- `HOST_MINIO_CONSOLE_PORT`

当前 worker 的本机前提：

- 仓库根目录下需要存在 `models/`，用于放置所有 checkpoint 和 body models
- 首次 `worker` 从零构建 GPU 镜像会比较慢
- 如需使用 `use_dpvo=true`，worker 镜像会额外编译安装 DPVO 及其依赖，构建时间会更长
- DPVO 扩展在 Docker build 阶段依赖显式的 `TORCH_CUDA_ARCH_LIST`，当前默认值是 `7.5;8.0;8.6;8.9`
- 如果远端机器的 GPU 架构不在默认列表中，需要在 `deploy/env/worker.remote.env` 中覆盖 `WORKER_TORCH_CUDA_ARCH_LIST`
- 上游 `GVHMR` 当前没有发布 tag，因此本仓库通过 submodule 固定 commit 而不是跟随最新 `main`
- worker 启动前会校验 CUDA、模型完整性、scratch 可写与最小剩余空间，以及 `Postgres/Redis/MinIO` 连通性

当前默认模型目录结构：

```text
models/
├── dpvo/dpvo.pth
├── gvhmr/gvhmr_siga24_release.ckpt
├── hmr2/epoch=10-step=25000.ckpt
├── vitpose/vitpose-h-multi-coco.pth
├── yolo/yolov8x.pt
└── body_models/
    ├── smpl/SMPL_{GENDER}.pkl
    └── smplx/SMPLX_{GENDER}.npz
```

这些文件不会在 Docker build 中自动下载。请按 [models/README.md](models/README.md) 的说明自行下载并放到对应位置。

## Env 文件约定

`deploy/env/` 统一采用两层：

- `*.example.env`：提交到仓库，作为模板
- `*.env`：本机或目标机器实际使用的运行配置，不纳入 git

初始化方式：

```bash
make env-init
```

如需强制用模板覆盖本地 env：

```bash
make env-init-force
```

当前模板包括：

- `deploy/env/api.example.env`
- `deploy/env/minio.example.env`
- `deploy/env/scheduler.example.env`
- `deploy/env/worker.example.env`
- `deploy/env/worker.remote.example.env`

## 远端 Worker 部署

更完整的远端 worker 部署步骤见：

- [deploy/README.remote-worker-deployment.md](deploy/README.remote-worker-deployment.md)

当前仓库提供两种远端 `worker-only` 方式：

- 推荐方式：通过 [deploy/scripts/render_remote_worker_compose.py](deploy/scripts/render_remote_worker_compose.py)
  根据 `WORKER_GPU_IDS` 生成“**任意 GPU 数量，一卡一 worker**”的 compose
- 兼容模板：
  - 单 worker 节点：[deploy/compose.worker.remote.yml](deploy/compose.worker.remote.yml)
  - 2 GPU 节点：[deploy/compose.worker.remote.2gpu.yml](deploy/compose.worker.remote.2gpu.yml)
- 环境变量模板：[deploy/env/worker.remote.example.env](deploy/env/worker.remote.example.env)
- 主机预检脚本：[deploy/scripts/check_worker_host.sh](deploy/scripts/check_worker_host.sh)

推荐流程：

1. 在远端 worker 机器上复制仓库
2. 运行 `make env-init`
3. 直接编辑 `deploy/env/worker.remote.env`，按机器实际情况填写控制平面地址、模型目录、GPU 列表和 scratch 根目录
   以及 `WORKER_TORCH_CUDA_ARCH_LIST`
4. 运行预检脚本：

```bash
bash deploy/scripts/check_worker_host.sh deploy/env/worker.remote.env
```

5. 用通用命令渲染并启动远端 worker：

```bash
make compose-remote-worker-config WORKER_REMOTE_ENV=deploy/env/worker.remote.env
make compose-remote-worker-up WORKER_REMOTE_ENV=deploy/env/worker.remote.env
```

上面这套会先根据 `WORKER_GPU_IDS` 生成：

- `deploy/.generated/compose.worker.remote.generated.yml`

再用它启动一组“一卡一 worker”的容器。

当前远端多卡部署只支持：

- 一个物理 GPU 对应一个 worker 容器

当前不支持：

- 同一物理 GPU 上同时跑多个 worker

例如：

```bash
WORKER_GPU_IDS=0
WORKER_GPU_IDS=0,1
WORKER_GPU_IDS=0,1,2,3
```

### Worker 命名规则

统一约定：

- `node_name = <机器名>`
- `worker_id = <node_name>-gpu<gpu_slot>`
- `gpu_slot = 宿主机 nvidia-smi 中的 GPU 序号`

示例：

- 单卡机器：
  - `WORKER_NODE_NAME=worker-bj-02`
  - `WORKER_GPU_IDS=0`
  - 生成 `worker-bj-02-gpu0`
- 2 卡机器：
  - `WORKER_GPU_IDS=0,1`
  - `worker-bj-03-gpu0`
  - `worker-bj-03-gpu1`
- 4 卡机器：
  - `WORKER_GPU_IDS=0,1,2,3`
  - `worker-bj-04-gpu0`
  - `worker-bj-04-gpu1`
  - `worker-bj-04-gpu2`
  - `worker-bj-04-gpu3`

当前 worker 启动时会做两类校验：

- `worker_id` 已被别的 `node_name/gpu_slot` 占用时拒绝启动
- `node_name + gpu_slot` 已被别的 `worker_id` 占用时拒绝启动
- `healthcheck` 失败或基础设施级错误会让 worker 直接退出，交给 Docker 自动拉起新实例

### 防火墙与网络

远端 worker 到控制平面机器至少需要访问：

- Postgres：默认 `15432/tcp`
- Redis：默认 `16379/tcp`
- MinIO API：默认 `19000/tcp`

MinIO Console 默认 `19001/tcp` 只给人工管理使用，worker 不依赖它。

### Scratch 策略

如果宿主机的 Docker data root 已经在本地 SSD 上，单 worker 节点不必额外再找一块单独磁盘。
但对远端多 worker 节点，仍然建议每个 worker 显式绑定独立的宿主机 scratch 目录，例如：

- `/srv/gvhmr-batch-process/scratch/gpu0`
- `/srv/gvhmr-batch-process/scratch/gpu1`

原因不是“必须更快”，而是：

- 每张卡的临时文件互不干扰
- 容易看磁盘占用和清理残留
- worker 出问题时更容易排障

当前远端 compose 模板默认就按“每个 worker 一个 host scratch 目录”来写。
通用渲染脚本默认会把：

- `WORKER_SCRATCH_ROOT=/srv/gvhmr-batch-process/scratch`

展开成：

- `/srv/gvhmr-batch-process/scratch/gpu0`
- `/srv/gvhmr-batch-process/scratch/gpu1`
- ...

另外，worker 会定期自动清理陈旧 scratch 目录：

- `succeeded / canceled`：默认保留 `1h`
- `failed`：默认保留 `7d`
- 数据库中已不存在的 orphan 目录：默认保留 `1d`
- 当前正在运行的 job 目录不会被清理

### DPVO 构建说明

- `use_dpvo=true` 需要 worker 镜像已经编译好 DPVO CUDA 扩展
- 本仓库默认通过 `WORKER_TORCH_CUDA_ARCH_LIST=7.5;8.0;8.6;8.9` 构建
- 本机当前已验证 `RTX 2080 Ti (7.5)` 可正常编译并运行 DPVO
- 如果远端机器是其他架构，例如 `H100 (9.0)`，需要在远端 env 中改成对应列表后重新 `docker compose ... up --build`

### 时间同步

远端 worker 的时间同步必须由宿主机保证。容器会继承宿主机时钟。

- 建议启用 `systemd-timesyncd` 或 `chrony`
- 预检脚本会检查主机 NTP 状态
- worker 启动时还会把自己的时间和 Postgres 时间做一次比对
- 漂移超过阈值默认拒绝启动，避免 heartbeat 和超时判定出错

### Worker 自愈行为

- worker 启动前 preflight 失败时，不会进入接单状态
- `scheduled` job 如果在阈值内一直没被 worker claim，会自动回到 `queued`
- 仅 `infra_transient` 故障会自动 retry，当前实现包括：
  - `CUDA runtime is unavailable`
  - `CUDA initialization failed`
  - `worker heartbeat timed out`
- 上述自动 retry 默认只执行 `1` 次，回退延迟默认 `30s`
- worker 运行中如果遇到 `CUDA unavailable`、模型缺失、存储/数据库关键失败等基础设施级问题，会退出并依赖 compose `restart` 拉起新实例
- 失败 job 会尽量把 `runner.log` 作为 artifact 上传，便于批处理排障

当前默认阈值：

- warning: `5s`
- fail: `30s`

## 快速开始

当前仓库已经从“定义已固化 + 骨架”进入“可运行的 Phase 2 垂直切片”状态。推荐先阅读：

1. `Project_Definitions/00_Project_Overview.md`
2. `Project_Definitions/02_System_Architecture.md`
3. `Project_Definitions/03_API_and_Data_Contracts.md`
4. `Project_Definitions/06_Development_Plan.md`

## 常用命令

```bash
make tree
make compose-local-config
make compose-local-up
make compose-local-down
make test-batch
```

## 测试目录约定

- `test/uploads/`：放待测视频，已加入 git ignore
- `test/results/`：保存 batch 状态和下载回来的产物，已加入 git ignore
- `test/run_batch_test.py`：批量上传 `test/uploads/` 下的视频，创建 batch，轮询完成，并把产物写入 `test/results/<timestamp>__<batch_id>/`
- `test/export_batch_npz.py`：把一个已下载 batch 中所有成功 job 的 `hmr4d_results.pt` 导出成 `SMPL-X body-only` 的 `.npz`
- 下载后的 job 目录会按 `job_id__原始文件名` 命名，并额外生成：
  - `job_index.json`
  - `job_index.csv`
  用来记录 `结果文件夹名 -> job_id -> upload_filename -> source_path`

示例：

```bash
python3 test/run_batch_test.py --video-render --video-type skeleton_only
```

将一个 batch 中所有成功输出的 `pt` 离线转换成 `.npz`：

```bash
python3 test/export_batch_npz.py test/results/<timestamp>__<batch_id>
```

该命令会在 batch 根目录下生成 `ouput/`，其中包含：

- `README.md`
- `index.json`
- `index.csv`
- `<job_id>__<video_stem>.npz`

这批 `.npz` 的约定是：

- `model_type = "smplx"`
- `pose_rep = "body_only"`
- `coordinate_system = "world_y_up"`
- `betas` 为序列级 `10D`
- `root_orient` 为 `(F, 3)`
- `pose_body` 为 `(F, 63)`
- `poses` 为 `(F, 22, 3)`，其中 `poses[:, 0, :] == root_orient`
- `trans` 为 `(F, 3)`

或：

```bash
make test-batch TEST_BATCH_ARGS="--video-render --video-type skeleton_only"
```

## 下一步

- 在第二台多 GPU worker 节点上完成真实多机验证
- 完成失败重试、运行中取消强化、worker 断线恢复
- 对 worker 运行时依赖做瘦身，减少镜像构建和分发成本
