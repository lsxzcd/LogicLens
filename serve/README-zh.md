# 推理服务（serve/）

赛题要求提交 `serve/`：**推理服务配置与启动脚本**（选题指南 3.1.5.1）。
指南 3.1.3.2 把"推理后端与服务参数、上下文长度与单次输出上限"划为**队伍自主**决定的部分，
所以这些选择集中记录在本目录，别处不要重复配置。

---

## 文件

| 文件 | 用途 |
|---|---|
| `start.sh` | 启动推理服务并等待就绪；**断网可用**，不下载任何东西 |
| `fetch-model.sh` | 一次性拉取权重。**唯一需要网络的步骤**，在构建镜像或首次部署时执行 |
| `record_service.py` | 从服务读取真实配置（版本/量化/摘要/显存/上下文）并输出，用于填 `MODEL.md` |
| `env.example` | 全部服务与采样参数及说明，复制为 `.env.serve` 后修改 |
| `README-zh.md` | 本文件 |

---

## 快速开始

```bash
# 1) 一次性：拉取权重（需要网络）
bash serve/fetch-model.sh qwen2.5-coder:1.5b

# 2) 启动服务（无需网络）
bash serve/start.sh --model qwen2.5-coder:1.5b

# 3) 另开一个终端：记录配置，用于 MODEL.md
python3 serve/record_service.py --model qwen2.5-coder:1.5b \
        --write model/service-measurements.json
```

Windows 上用 Ollama 自带的应用启动，其余步骤相同。本机实际使用的模型目录为
`D:\JZDSLx\ollama_models`（C 盘空间紧张，见 `docs/status-log-zh.md` §3.4）。

---

## 断网要求（赛题的硬约束）

容器在**断网沙箱**中运行，必须自行完成从读题到产码。因此：

| 要求 | 本目录如何满足 |
|---|---|
| 不依赖任何网络调用 | `start.sh` 不做任何下载；只连本机 `127.0.0.1:11434` |
| 权重必须已在容器内或已挂载 | `start.sh` 在启动前**检查权重目录非空，为空则直接失败并说明原因** |
| 路径不能依赖外部环境 | 全部经环境变量，默认值可用 |

> ⚠️ **`start.sh` 的权重检查是故意的**：如果权重不在，容器会在评测时静默失败；
> 提前报错比事后排查便宜得多。

---

## 为什么权重放在挂载卷而不是打进镜像

| 方案 | 镜像大小 | 优点 | 缺点 |
|---|---|---|---|
| 权重打进镜像 | 数 GB ~ 十几 GB | 完全自包含，不依赖挂载 | 分发慢；每次换模型都要重建镜像 |
| **权重放挂载卷**（推荐） | 几百 MB | 换模型只改环境变量；镜像小 | 依赖挂载正确 |

赛题允许队伍自主选择模型与量化，所以**换模型是常态**——挂载卷方案更合适。
若赛事方最终要求完全自包含，把权重目录 `COPY` 进镜像即可，`start.sh` 无需改动。

---

## 显存约束（赛题硬指标）

赛题要求模型**能完整容纳于单张 32 GB 显卡，不允许跨卡**。测量方式：

```bash
python3 serve/record_service.py --model <模型名> --json
```

关键字段是 **`size_vram`**（Ollama `/api/ps` 返回）：

- **`size_vram > 0`** → 模型已驻留显存，值即实际显存占用 → **写进 `MODEL.md`**
- **`size_vram = 0`** → 模型在系统内存中，**未证明 GPU 驻留**

> 本机（Intel 核显，无独显）实测 `size_vram = 0`，所以**本机数据不能用于证明显存约束**。
> 必须在学校的 AMD 机器上重跑，见 `docs/amd-machine-validation-zh.md`。

`record_service.py` 还会尝试 `rocm-smi` / `nvidia-smi` 作为**第二个来源**；两者都不可用时
明确记为 `unavailable`，而不是静默跳过。

---

## 已验证 / 未验证

| 项目 | 状态 |
|---|---|
| `record_service.py` 在真实 Ollama 上运行 | ✅ 本机实测，输出全部字段 |
| 从服务读到量化/摘要/模型上下文长度 | ✅ `Q4_K_M`、`context_length=32768` |
| 检测到"未驻留显存"并说明 | ✅ 本机 `size_vram=0` 被识别并标注 |
| `start.sh` / `fetch-model.sh` 在 Linux 容器内运行 | ❌ **未验证**——本机无 Docker、无 Linux 环境 |
| AMD ROCm 下的真实显存占用 | ❌ **未验证**——需 AMD 显卡 |

`start.sh` 与 `fetch-model.sh` 是标准的 bash + `set -euo pipefail`，逻辑简单，
但**在容器里跑通之前不算验证过**。这一点在 `docs/status-log-zh.md` 中同样如实记录。
