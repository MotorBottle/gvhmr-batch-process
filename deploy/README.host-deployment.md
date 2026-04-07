# Host Deployment

这份文档用于部署主节点，也就是控制平面。

主节点负责运行：

- `postgres`
- `redis`
- `minio`
- `migrate`
- `api`
- `scheduler`

如果这台机器也要顺带跑本地 GPU worker，再额外使用 [compose.worker.yml](./compose.worker.yml)。

## 1. 前置条件

- 已安装 `Docker`
- 已安装 `Docker Compose` plugin
- 已拉取仓库到本机
- 已初始化 submodule：

```bash
git submodule update --init --recursive
```

## 2. 初始化环境文件

在仓库根目录执行：

```bash
make env-init
```

这会从 `deploy/env/*.example.env` 生成本地运行配置：

- `deploy/env/api.env`
- `deploy/env/minio.env`
- `deploy/env/scheduler.env`
- `deploy/env/worker.env`

如需覆盖已有文件：

```bash
make env-init-force
```

## 3. 按需修改主节点配置

通常需要确认或调整：

- `deploy/env/api.env`
- `deploy/env/minio.env`
- `deploy/env/scheduler.env`

常见关注项：

- `Postgres / Redis / MinIO` 连接参数
- API 对外端口
- MinIO 用户名、密码、bucket

默认宿主机端口来自 [compose.control-plane.yml](./compose.control-plane.yml)：

- API：`18000`
- Postgres：`15432`
- Redis：`16379`
- MinIO API：`19000`
- MinIO Console：`19001`

如需覆盖，可在启动前导出：

```bash
export HOST_API_PORT=18000
export HOST_POSTGRES_PORT=15432
export HOST_REDIS_PORT=16379
export HOST_MINIO_PORT=19000
export HOST_MINIO_CONSOLE_PORT=19001
```

## 4. 启动主节点

只启动控制平面：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  up --build -d
```

如果这台主节点也要跑本地 GPU worker：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  -f deploy/compose.worker.yml \
  up --build -d
```

## 5. 校验主节点状态

查看容器：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  ps
```

如果包含本地 worker，就加上 `-f deploy/compose.worker.yml`。

检查 API 健康：

```bash
curl http://127.0.0.1:${HOST_API_PORT:-18000}/health
```

检查 Web 面板：

```text
http://127.0.0.1:18000/
```

当前 Web 面板会自动显示：

- 组件状态
- worker 状态
- 活动 job
- 活动 batch

## 6. 主节点对外放通的端口

如果需要远端 worker 接入，主节点至少要放通：

- `15432/tcp`：Postgres
- `16379/tcp`：Redis
- `19000/tcp`：MinIO API

如果客户端或浏览器要从其他机器访问 API / Web，还需要放通：

- `18000/tcp`：API + Web UI

MinIO Console 只用于人工管理，通常按需放通：

- `19001/tcp`

## 7. 常用命令

停止主节点：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  down
```

查看主节点日志：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  logs -f api scheduler postgres redis minio
```

如果本机也跑 worker：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  -f deploy/compose.worker.yml \
  logs -f worker
```
