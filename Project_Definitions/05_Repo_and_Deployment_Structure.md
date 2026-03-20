# 仓库结构与部署结构

## 1. 仓库结构

```text
repo/
├── Project_Definitions/
├── deploy/
│   ├── compose.base.yml
│   ├── compose.control-plane.yml
│   ├── compose.worker.yml
│   ├── compose.dev.yml
│   ├── docker/
│   └── env/
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

### compose.dev.yml

- 源码挂载
- reload
- 开发环境覆盖配置

## 4. 环境变量边界

### 控制平面

- `POSTGRES_DSN`
- `REDIS_URL`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

### Worker

- `WORKER_ID`
- `NODE_NAME`
- `GPU_SLOT`
- `MODEL_ROOT`
- `SCRATCH_ROOT`
- `UPSTREAM_GVHMR_REF`
- `RUNNER_ENTRY_MODULE`

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

- 各类 checkpoint
- body models

### 本地 scratch

- 临时视频
- 中间文件
- 局部 cache

## 6. 迁移原则

- 不使用“API 容器本地结果目录”作为系统真源
- 不让 worker 依赖某个特定宿主机路径的最终结果
- 所有核心状态必须可在无共享文件系统场景下成立

## 7. 当前单机实现约束

- 当前 compose 默认宿主机端口使用高位端口，避免与旧仓库冲突
- worker 当前默认复用：
  - `/home/synapath/gvhmr/models`
  - `/home/synapath/gvhmr/body_models`
- worker 当前直接从 CUDA 基础镜像和 `third_party/GVHMR` submodule 自行构建
- worker 启动需等待 `migrate` 完成，避免在表尚未创建时抢跑
