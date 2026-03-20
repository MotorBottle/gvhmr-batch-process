# 测试与验收

## 1. 文档验收

- `Project_Definitions` 八个核心文档齐全
- 文档之间术语一致、接口一致、状态一致
- 没有阻塞实现的空白定义

## 2. API 验收

- `POST /uploads` 返回 upload 元数据
- `POST /jobs` 可创建 job
- `GET /jobs/{job_id}` 可读状态
- `POST /jobs/{job_id}/cancel` 可取消
- `POST /batches` 可创建 batch
- `GET /batches/{batch_id}` 可读统计
- `GET /workers` 可读 worker 信息
- `GET /health` 可读服务健康信息

## 3. Web 验收

- 可以上传视频
- 可以创建 job
- 可以创建 batch
- 可以查看 job/batch 状态
- 可以查看当前 API 的基础信息

## 4. 单机执行验收

- 单 worker 单 GPU 可完成真实执行
- 多 worker 多 GPU 可并发执行不同 job
- 同一 GPU 不会被重复分配

## 5. 多机验收

- worker 节点不与控制平面同机时仍可接任务
- worker 执行完成后产物可通过 API 下载

## 6. 故障验收

- worker 失联后状态可被识别
- scheduler 重启后不丢失元数据
- job 失败时能记录失败原因

## 7. 缓存验收

- 相同视频重复处理命中核心缓存
- 仅改渲染参数时不重复跑主推理

## 8. 发布门槛

- 关键接口有基本测试
- compose 文件能启动控制平面
- 项目定义文档和代码结构保持一致

