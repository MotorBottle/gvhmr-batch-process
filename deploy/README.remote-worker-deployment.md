# Remote Worker Deployment

这份文档用于部署远端 `worker-only` 节点。

远端 worker 节点只运行 GPU worker，不运行：

- `postgres`
- `redis`
- `minio`
- `api`
- `scheduler`

它会连接到已经运行中的主节点控制平面。

当前方案只支持：

- 一张物理 GPU 对应一个 worker 容器

当前不支持：

- 同一张物理 GPU 上同时跑多个 worker

## 1. 前置条件

远端机器需要具备：

- `Docker`
- `Docker Compose` plugin
- `NVIDIA driver`
- `NVIDIA Container Toolkit`
- `nvidia-smi` 正常
- 本地模型目录

仓库初始化：

```bash
git clone <your-repo-url>
cd gvhmr-batch-process
git submodule update --init --recursive
make env-init
```

## 2. 准备远端 worker env

`make env-init` 已经会生成：

- [deploy/env/worker.remote.env](./env/worker.remote.env)

所以这里直接编辑这个文件即可。

如果你没有运行 `make env-init`，也可以手动初始化：

```bash
cp deploy/env/worker.remote.example.env deploy/env/worker.remote.env
```

必须确认的核心字段：

- `WORKER_NODE_NAME`
- `MODEL_ROOT`
- `WORKER_GPU_IDS`
- `WORKER_SCRATCH_ROOT`
- `GVHMR_BATCH_WORKER_POSTGRES_DSN`
- `GVHMR_BATCH_WORKER_REDIS_URL`
- `GVHMR_BATCH_WORKER_MINIO_ENDPOINT`

一个双卡机器的典型例子：

```env
WORKER_NODE_NAME=worker-2080ti-122
MODEL_ROOT=/home/synapath/gvhmr-batch-process/models
WORKER_GPU_IDS=0,1
WORKER_SCRATCH_ROOT=/home/synapath/gvhmr-batch-process/scratch

GVHMR_BATCH_WORKER_POSTGRES_DSN=postgresql://postgres:postgres@192.168.1.10:15432/gvhmr_batch_process
GVHMR_BATCH_WORKER_REDIS_URL=redis://192.168.1.10:16379/0
GVHMR_BATCH_WORKER_MINIO_ENDPOINT=192.168.1.10:19000
GVHMR_BATCH_WORKER_MINIO_ACCESS_KEY=minioadmin
GVHMR_BATCH_WORKER_MINIO_SECRET_KEY=minioadmin
GVHMR_BATCH_WORKER_MINIO_BUCKET=gvhmr-batch-process
GVHMR_BATCH_WORKER_MINIO_SECURE=false
```

## 3. GPU 列表和命名规则

通过：

```env
WORKER_GPU_IDS=0,1,2,3
```

声明要使用哪些 GPU。

含义是：

- GPU0 启动一个 worker
- GPU1 启动一个 worker
- GPU2 启动一个 worker
- GPU3 启动一个 worker

`gpu_slot` 对应宿主机 `nvidia-smi` 序号。

worker 命名规则固定为：

- `worker_id = <WORKER_NODE_NAME>-gpu<gpu_slot>`

例如：

- `WORKER_NODE_NAME=worker-2080ti-122`
- `WORKER_GPU_IDS=0,1`

会生成：

- `worker-2080ti-122-gpu0`
- `worker-2080ti-122-gpu1`

## 4. 模型目录与 scratch 目录

`MODEL_ROOT` 必须是远端机器自己的本地路径，并且存在。

当前 worker 会把它挂载到容器里的：

- `/app/gvhmr/inputs/checkpoints`

推荐模型目录：

```text
/home/synapath/gvhmr-batch-process/models
```

`WORKER_SCRATCH_ROOT` 用于自动展开每张卡自己的临时目录：

```text
/home/synapath/gvhmr-batch-process/scratch/gpu0
/home/synapath/gvhmr-batch-process/scratch/gpu1
...
```

如果你想手工指定某张卡的宿主机路径，也可以在 env 里覆盖：

- `GPU0_SCRATCH_HOST_PATH`
- `GPU1_SCRATCH_HOST_PATH`

如果你想手工指定 `NVIDIA_VISIBLE_DEVICES` 映射，也可以覆盖：

- `GPU0_VISIBLE_DEVICE`
- `GPU1_VISIBLE_DEVICE`

默认情况下，每个 worker 直接使用同编号 GPU。

## 5. 运行预检

启动前先跑：

```bash
bash deploy/scripts/check_worker_host.sh deploy/env/worker.remote.env
```

这个脚本会检查：

- Docker
- Compose plugin
- `nvidia-smi`
- 模型目录是否存在
- scratch 目录是否存在/可创建
- 到主节点的 `Postgres / Redis / MinIO` 连通性
- 时间同步状态
- `WORKER_GPU_IDS` 中的每张卡是否真实存在

## 6. 生成并启动远端 worker compose

先渲染生成 compose：

```bash
make compose-remote-worker-config WORKER_REMOTE_ENV=deploy/env/worker.remote.env
```

这一步会先调用：

- [deploy/scripts/render_remote_worker_compose.py](./scripts/render_remote_worker_compose.py)

并生成：

- `deploy/.generated/compose.worker.remote.generated.yml`

然后启动：

```bash
make compose-remote-worker-up WORKER_REMOTE_ENV=deploy/env/worker.remote.env
```

停止：

```bash
make compose-remote-worker-down WORKER_REMOTE_ENV=deploy/env/worker.remote.env
```

## 7. 启动后验证

在远端机器本地看容器：

```bash
docker compose -f deploy/.generated/compose.worker.remote.generated.yml ps
```

看日志：

```bash
docker compose -f deploy/.generated/compose.worker.remote.generated.yml logs -f
```

在主节点看 worker 是否注册成功：

```bash
curl http://<主节点IP>:18000/workers
curl http://<主节点IP>:18000/dashboard/overview
```

或者直接打开主节点 Web 面板：

```text
http://<主节点IP>:18000/
```

正常情况下会看到新增 worker：

- `<WORKER_NODE_NAME>-gpu0`
- `<WORKER_NODE_NAME>-gpu1`
- ...

## 8. 主节点需要放通的端口

远端 worker 到主节点至少要通：

- `15432/tcp`：Postgres
- `16379/tcp`：Redis
- `19000/tcp`：MinIO API

`19001/tcp` 不是 worker 必需，只给 MinIO Console。

## 9. 常见问题

### `line XX: 8.0: command not found`

说明 `WORKER_TORCH_CUDA_ARCH_LIST` 没有加引号。

正确写法：

```env
WORKER_TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9"
```

### `MODEL_ROOT does not exist`

说明远端机器本地模型目录不存在。

需要：

- 先把模型拷到远端机器
- 再让 `MODEL_ROOT` 指向远端的真实本地路径

### 需要双卡、四卡甚至更多卡

直接改：

```env
WORKER_GPU_IDS=0,1
WORKER_GPU_IDS=0,1,2,3
```

不需要再单独维护新的固定 compose 文件。
