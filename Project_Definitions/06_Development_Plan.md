# 开发计划

## Phase 0：定义固化

交付物：

- `Project_Definitions` 全套文档
- 仓库结构定稿
- API、状态机、部署边界定稿

完成标准：

- 无阻塞实现的 TBD
- 关键名词、状态、接口名称全部固定

## Phase 1：骨架搭建

交付物：

- monorepo 目录结构
- API/Scheduler/Worker 基础代码骨架
- compose 分层文件
- Dockerfile 与 env 模板

完成标准：

- 服务可独立启动
- 基础健康检查和页面可访问

## Phase 2：元数据与对象存储

交付物：

- Postgres 模型
- MinIO 存储抽象
- Upload/Job/Batch/Artifact 持久化

完成标准：

- `upload/job/batch` 不再依赖内存存储
- 服务重启后元数据不丢失

当前状态：

- 已完成
- 已落地 Alembic、SQLAlchemy、MinIO SDK
- 本机 compose 已验证 `upload -> job -> artifact download` 闭环

## Phase 3：GVHMR Runner

交付物：

- 对 GVHMR 的标准执行封装
- 核心缓存键
- 单 job 产物清单输出

完成标准：

- 单 worker 单 GPU 可完成一次真实 GVHMR 处理

当前状态：

- 已完成单机单卡接入
- 当前通过 worker subprocess 调用 `demo_with_skeleton.py`
- 已验证真实视频处理成功并产出：
  - `hmr4d_results.pt`
  - `bbx.pt`
  - `vitpose.pt`
  - `vit_features.pt`
  - `runner.log`

## Phase 4：Scheduler 与 Worker 联调

交付物：

- Redis 队列
- worker heartbeat
- assignment 逻辑
- 取消和失败回写

完成标准：

- job 从 queued 到 succeeded/failed/canceled 全链路跑通

当前状态：

- 已完成单机单卡最小联调版本
- 当前采用 `Scheduler + Postgres polling`，Redis 仍未进入关键路径
- 已验证：
  - `queued -> running -> succeeded`
  - `queued -> canceled`
  - `running -> canceled`
  - batch 聚合计数

## Phase 5：Batch 与缓存

交付物：

- batch API
- 批次状态统计
- 内容寻址缓存
- 单机多 GPU 并发

完成标准：

- 多个 job 可并发执行
- 重复任务能命中缓存

## Phase 6：基础 Web 控制台

交付物：

- 上传页面
- job 创建页面
- batch 创建页面
- 状态查看页面
- 下载入口

完成标准：

- 非命令行用户也能完成完整任务流程

## Phase 7：多机验证与发布准备

交付物：

- 多机 worker 接入验证
- 稳定性测试
- 部署说明补全

完成标准：

- 控制平面与 worker 可分机部署并稳定运行
