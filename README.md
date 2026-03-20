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
- Scheduler 基于 Postgres 轮询分配任务
- Worker 已接入真实 GVHMR 执行链路，并写回真实 `hmr4d_results.pt` 与预处理产物
- 上游 `GVHMR` 以 git submodule 固定到 `088caff492aa38c2d82cea363b78a3c65a83118f`

## 本机启动

```bash
git submodule update --init --recursive

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

- 默认复用旧仓库模型目录：`/home/synapath/gvhmr/models`
- 默认复用旧仓库 body model 目录：`/home/synapath/gvhmr/body_models`
- 首次 `worker` 从零构建 GPU 镜像会比较慢
- 上游 `GVHMR` 当前没有发布 tag，因此本仓库通过 submodule 固定 commit 而不是跟随最新 `main`

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
- `test/run_batch_test.py`：批量上传 `test/uploads/` 下的视频，创建 batch，轮询完成，并把产物写入 `test/results/<batch_id>/`

示例：

```bash
python3 test/run_batch_test.py --video-render --video-type skeleton_only
```

或：

```bash
make test-batch TEST_BATCH_ARGS="--video-render --video-type skeleton_only"
```

## 下一步

- 引入 Redis 消息通道，替换当前 Postgres polling 调度路径
- 完成失败重试、运行中取消强化、多机 worker 验证
