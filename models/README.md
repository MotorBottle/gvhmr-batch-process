# 模型目录说明

本仓库不会在 Docker build 期间自动下载 `GVHMR` 所需的模型文件。请先手动下载，再放入本目录。

默认目录结构如下：

```text
models/
├── dpvo/
│   └── dpvo.pth
├── gvhmr/
│   └── gvhmr_siga24_release.ckpt
├── hmr2/
│   └── epoch=10-step=25000.ckpt
├── vitpose/
│   └── vitpose-h-multi-coco.pth
├── yolo/
│   └── yolov8x.pt
└── body_models/
    ├── smpl/
    │   └── SMPL_{GENDER}.pkl
    └── smplx/
        └── SMPLX_{GENDER}.npz
```

来源说明：

- `SMPL` / `SMPLX`：按上游要求到官方站点注册后下载
- 其他权重：按上游 `GVHMR` 安装文档提供的链接下载

上游参考：

- [third_party/GVHMR/docs/INSTALL.md](../third_party/GVHMR/docs/INSTALL.md)

运行 `worker` 时，本目录会默认挂载到容器内的 `/app/gvhmr/inputs/checkpoints`。

如需改用其他宿主机目录，可在运行 compose 前设置：

```bash
export MODEL_ROOT=/abs/path/to/your/models
```

然后再执行：

```bash
docker compose \
  -f deploy/compose.base.yml \
  -f deploy/compose.control-plane.yml \
  -f deploy/compose.worker.yml \
  up --build -d
```
