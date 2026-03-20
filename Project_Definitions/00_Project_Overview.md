# GVHMR Batch Process 项目总览

## 1. 项目目标

`GVHMR Batch Process` 的目标是把原始 `GVHMR` 从单机 demo 式推理工具，升级为面向工程使用的批处理和集群处理框架。

核心目标：

- 支持批量提交视频并统一管理执行过程
- 支持单机多 GPU 并发处理
- 支持多机 worker 横向扩展
- 把输入、输出、日志、状态统一纳入平台化管理
- 形成明确的控制平面 / 执行平面分层

## 2. 非目标

第一阶段明确不做以下内容：

- 兼容旧版同步 `/process` 接口
- 多租户系统、项目级权限、配额管理
- 公网开放服务能力
- Kubernetes 部署与 Helm Chart
- 完整可观测平台
- 训练、微调、分布式训练能力
- 单任务跨多 GPU 推理并行

## 3. 目标用户

- 内网研发团队
- 需要批量处理动作视频的算法/产品工程师
- 负责部署单机多卡或小型 GPU 集群的工程人员

## 4. 设计原则

- `API-first`：所有核心能力都通过明确的 API 暴露
- `Batch-first`：批处理是一级能力，不是附加脚本
- `Cluster-ready`：从第一天开始分离控制平面和 GPU 执行平面
- `Storage-backed`：输入、输出、日志要落到统一存储
- `Single-repo`：单仓库管理所有核心服务和共享契约
- `Migration-friendly`：保留未来迁移到 K8s 的边界

## 5. 核心术语

- `Upload`：平台接收的原始视频对象
- `Job`：对单个视频的一次处理任务
- `Batch`：一组 job 的集合
- `Artifact`：job 执行过程中产生的输出对象
- `Worker`：绑定单张 GPU 的执行进程/容器
- `Scheduler`：负责选择任务和分发执行位置的服务
- `Control Plane`：API、Scheduler、Postgres、Redis、MinIO 等管理层
- `Execution Plane`：GPU worker 所在节点与本地模型卷

## 6. 第一阶段边界

第一阶段必须交付：

- 异步 API
- 批处理能力
- 基础 Web 控制台
- Redis 队列
- Postgres 元数据存储
- MinIO 对象存储
- 单机多 GPU worker 并发
- 多机 worker 接入能力

第一阶段可以先简化但不能违背架构边界的点：

- UI 只做基础任务面板
- worker/scheduler 的策略先采用 `优先级 + FIFO`
- 日志和指标先保留基础结构，不做完整观测平台

## 7. 成功标准

如果系统达到以下状态，则认为第一阶段方向正确：

- 用户可以上传多个视频并创建 batch
- 平台可以把 job 分发到多个 GPU worker
- 执行状态可以稳定查询
- 结果与日志可以统一下载
- 更换为多机 worker 时不需要改 API 设计

## 8. 当前里程碑状态

截至当前迭代，已经完成：

- 单机单卡 Docker Compose 垂直切片
- Postgres + MinIO 控制平面真落地
- Scheduler + Worker 真正联调
- 真实 GVHMR runner 接入，已验证生成 `hmr4d_results.pt`
- 上游 `GVHMR` 已以 submodule 形式固定到 commit `088caff492aa38c2d82cea363b78a3c65a83118f`

当前仍保留的过渡性约束：

- Scheduler 关键路径仍基于 Postgres polling
- Redis 仍未进入关键调度路径
