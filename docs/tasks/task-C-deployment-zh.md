# 队友 C · 第一周任务书：部署与容器（实验室机器）

> **这份文档可以直接转发给队友，不需要额外口头解释。**
> 有问题先看文末「卡住了怎么办」。

---

## 0. 背景（30 秒版）

我们在做一个**本地 RTL 设计智能体**（LogicLens），参加全国大学生嵌入式芯片与系统设计竞赛 AMD FPGA 赛道 RTL Track。

它做的事：**读自然语言题目 → 本地模型生成 Verilog → 真实 Vivado 三级判定 → 失败就局部修复**。

**你的方向**：让提交物在**实验室机器**上真的能跑，并产出 `MODEL.md` 需要的实测数据。

### 为什么你是**全局瓶颈**

赛题硬性要求：

> 模型须能在**单张 AMD 显卡（32 GB）**上完整容纳，**不允许跨卡**。

**而目前没有人知道实验室那台机器的显卡型号和显存。**
不知道显卡 → 定不了模型 → 出不了正式性能数据 → 报告第 7 节空着。

**所以你的第一个任务（环境勘察）优先于所有人的其他工作。**

---

## 1. 现状：我们卡在哪（必读）

### 1.1 开发机没有独立显卡

开发机实测只有 **Intel Iris Xe 核显**（无 AMD、无 NVIDIA）。所以：

| 项目 | 状态 |
|---|---|
| 三级判定（编译/仿真/综合） | ✅ 已在目标器件上实测通过 |
| 模型接入链路 | ✅ 已用 CPU 小模型（1.5B）打通 |
| **实测显存占用** | ❌ **没有**——本机 `size_vram = 0` |
| **容器在 Linux 下运行** | ❌ **从未验证**——本机是 Windows 且无 Docker |
| **全量 156 题正式数据** | ❌ 没有 |

**你的任务就是消掉这三条 ❌。**

### 1.2 实验室机器信息（已确认）

| 项目 | 值 |
|---|---|
| 访问方式 | **网易 UU 远程** |
| **设备 ID** | **201997749** |
| 主机名 | `jcsylvm1` |
| 设备名 | 虚拟机1 |
| **环境类型** | **Linux 虚拟机** |

**访问步骤**：UU 远程 → 左侧「远程协助」→ 在「伙伴的设备ID」填 `201997749` → 点「连接」。

> ⚠️ **建议从聊天记录复制粘贴，不要手打。** 曾把 ID 输成 `120199774`（同一批数字错位），
> 报错是"设备ID错误或不存在"，白折腾很久。

---

## 2. 任务 C1：环境勘察（**最高优先级，第一天就做**）

**目标**：产出一份环境事实清单。**这是决定模型选型的唯一依据。**

### 2.1 显卡与 ROCm

```bash
# 显卡型号
lspci | grep -i -E "vga|display|3d"

# ROCm 是否可用 + 显卡架构
rocminfo 2>/dev/null | head -40

# 显存
rocm-smi --showmeminfo vram 2>/dev/null || rocm-smi 2>/dev/null

# 驱动版本
cat /sys/module/amdgpu/version 2>/dev/null
```

**要记录**：显卡型号、显存总容量、`gfx` 架构代号（如 `gfx1030`）、ROCm 版本。

**预期**：
- 如果有 `gfx` 输出 → ROCm 可用 ✅
- 如果 `rocminfo` 不存在或无输出 → 需要走 **Vulkan 回退**（见下）

> **注意**：赛题指南提到 **RDNA2 / RX 6000 系列**在某些驱动下不暴露 ROCm v7，
> 这时 **Vulkan** 是推荐回退路径。

### 2.2 Vulkan 可用性（ROCm 不行时的备选）

```bash
vulkaninfo 2>/dev/null | head -30 || echo "vulkaninfo 未安装"
ls /usr/share/vulkan/icd.d/ 2>/dev/null
```

### 2.3 工具链

```bash
# Vivado / Vitis
which vivado xvlog xelab xsim vitis 2>/dev/null
vivado -version 2>/dev/null | head -3

# 目标器件是否存在
ls /opt/Xilinx/Vivado/*/data/parts/xilinx/zynquplus/ 2>/dev/null | head
# 或 Vivado 已装的话：
# vivado -mode batch -source <(echo "puts [get_parts xczu3eg*]")
```

**要记录**：Vivado 版本、安装路径、**`xczu3eg-sbva484-1-e` 是否可用**。

### 2.4 容器与 Python

```bash
which docker podman 2>/dev/null; docker --version 2>/dev/null
python3 --version
nproc              # CPU 核数（影响并行评测）
free -g            # 内存
df -h /            # 磁盘空间（模型要几 GB ~ 几十 GB）
```

### 2.5 产出格式（**贴到群里**）

```
=== 实验室机器环境勘察 ===
日期：<填>
显卡型号      ：
显存总量      ：
gfx 架构      ：
ROCm 版本     ：
Vulkan 可用   ：是 / 否
Vivado 版本   ：
目标器件可用  ：是 / 否
Docker 可用   ：是 / 否
Python 版本   ：
CPU 核数      ：
内存          ：
磁盘可用      ：
```

**这份清单贴出来，其他人才能开始选模型和跑评测。**

---

## 3. 任务 C2：验证 `serve/` 与容器

### 3.1 为什么这一步现在特别有价值

`serve/*.sh` 和 `Dockerfile` 都写好了，但状态是 **"未验证"**——因为开发机是 Windows 且无 Docker。

**在 Linux 上跑通它们，能把报告里 4 条"未验证"变成已测。**
这比先跑模型评测更划算：**脚本是评测的载体**，载体不可靠，数据也不可靠。

### 3.2 先读一遍要验证的文件

```bash
cat serve/README-zh.md        # 设计说明与已知限制
cat serve/start.sh            # 启动服务
cat serve/fetch-model.sh      # 拉取权重（唯一需要网络的步骤）
cat serve/record_service.py   # 记录配置（填 MODEL.md 用）
cat Dockerfile
```

**关键设计**（理解这个才知道怎么测）：

- `start.sh` / `entrypoint.sh` **不做任何下载**，只连本机 `127.0.0.1`
- **权重缺失时直接报错退出**——这是故意的。断网沙箱里静默失败的代价太高
- 权重默认放挂载卷（`/models`），换模型只改环境变量

### 3.3 验证步骤

**第一步：装推理服务**

```bash
# Linux 用官方脚本
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

> ⚠️ 注意：GitHub 上那个 `ollama-windows-amd64-rocm.zip`（255 MB）是 **Windows 专用**，
> Linux 上**不要用错**。

**第二步：拉权重到非系统盘**

```bash
export OLLAMA_MODELS=/path/to/big/disk/ollama_models
mkdir -p "$OLLAMA_MODELS"
bash serve/fetch-model.sh <模型名>
ollama list
```

**第三步：验证 `start.sh`**

```bash
bash serve/start.sh --model <模型名>
```

**检查点**：
- [ ] 能启动并打印 "inference service is ready"
- [ ] **权重目录为空时会明确报错退出**（可以故意测：`OLLAMA_MODELS=/tmp/empty bash serve/start.sh`）

**第四步：记录配置（这是 `MODEL.md` 要的数据）**

```bash
python3 serve/record_service.py --model <模型名> --json
```

**关键看 `size_vram`**：

| 值 | 含义 |
|---|---|
| `size_vram > 0` | ✅ 模型已驻留显存，**这个值就是实测显存占用**，写进 `MODEL.md` |
| `size_vram == 0` | ❌ 回退到 CPU 了。**要查驱动/ROCm**，不能直接跑评测 |

**第五步：构建容器**

```bash
# 官方基础镜像名还没公布，先用个占位验证结构
docker build --build-arg BASE_IMAGE=ubuntu:24.04 -t logiclens .
```

**注意**：这一步**可能因为缺 Vivado 而失败**（官方镜像里才带 Vivado/Vitis），
这属于**预期情况**。要记录的是"结构是否合理、报错是否可理解"。

**第六步：断网验证（赛题硬要求）**

```bash
docker run --rm --network none -v "$OLLAMA_MODELS":/models logiclens --check
```

**期望**：容器在**无网络**下完成自检。

> 如果 `--check` 通过但完整运行失败，把完整输出贴出来。

### 3.4 发现问题怎么办

**在 PR 里说明**，附：
- 完整命令
- 完整输出
- 你判断的原因

**不要**默默改脚本——`serve/` 归你，但改动要能解释。

---

## 4. 任务 C3：模型选型与实测

### 4.1 选型约束（赛题硬指标）

> **单张 32 GB 显卡内完整容纳，不允许跨卡。**

所以选型由**显存**决定，不是由参数量决定。按显存粗估：

| 显存 | 可行量级 | 参考 |
|---|---|---|
| 32 GB | 7B（FP16 ≈ 14 GB）或 32B（Q4 ≈ 20 GB） | `qwen2.5-coder:32b` Q4_K_M |
| 48 GB | 32B 可上更高量化 | Q6/Q8 ≈ 27~35 GB |
| < 32 GB | 需要更小模型或更低量化 | 记录实际限制 |

### 4.2 实测方法

对每个候选模型：

```bash
ollama pull <候选>
python3 serve/record_service.py --model <候选> --json
```

**记录**：`size_vram`、`quantization`、`digest`、`parameter_size`

再跑一组小规模评测看质量：

```bash
export LOGICLENS_MODEL_URL="http://127.0.0.1:11434/v1"
export LOGICLENS_MODEL_NAME="<候选>"
export LOGICLENS_SEED=1

python3 eval.py --dataset experiments/data/verilogeval \
    --mode agent --limit 10 --samples 1 \
    --out experiments/results/model_selection/<候选名>
```

**注意时间预算**：单题约 85 秒（其中综合占 85%）。10 题约 15 分钟。

### 4.3 产出：填入 `model/MODEL.md` §4

`MODEL.md` 里标了 **[待测]** 的字段，你需要填：

- 模型仓库地址 + 版本/权重摘要（`record_service.py` 的 `digest`）
- 量化方式
- **实测显存占用**（`size_vram`）
- 上下文长度与最大输出长度
- 是否微调

---

## 5. 交付物与验收标准

| 交付物 | 验收标准 |
|---|---|
| **C1 环境勘察清单** | 显卡型号、显存、ROCm 版本、Vivado 版本、Docker 可用性，**都有命令输出为证** |
| **C2 脚本与容器验证** | `serve/start.sh`、`record_service.py`、`--network none` 都实际跑过；有完整日志 |
| **C3 模型选型** | 2~3 个候选的 `size_vram` 对比；选定主模型并说明理由 |
| `MODEL.md` §4 定稿 | `size_vram > 0` 且 < 32 GB，**有 `record_service.py` 输出为证** |

---

## 6. 边界：**不要动**这些文件

| 文件 | 归属 | 原因 |
|---|---|---|
| `vivado/run_flow.tcl` | D（协调人） | **判定口径** |
| `agent/controller.py` | B | 判定主路径 |
| `agent/task_parser.py`、`agent/rtl_lint.py` | B | |
| `skill/skill_cards.json` | A | |

**你可以放心动**：`serve/`、`Dockerfile*`、`model/MODEL.md`

---

## 7. 提交方式

```bash
git checkout -b deploy/<你的任务>-<你的名字>
# ... 开发 ...
python3 -m unittest discover -s tests        # 必须全绿

# ⚠️ 关键一步：用干净克隆验证
cd /tmp && git clone --branch <你的分支> --single-branch https://github.com/lsxzcd/LogicLens.git clean_check
cd clean_check && python3 -m unittest discover -s tests
# 预期 OK

git push -u origin deploy/<你的任务>-<你的名字>
```

然后开 PR。

> **注意**：`serve/*.sh` **必须保持 LF 行尾**。`.gitattributes` 已配置，但如果你在 Windows 上
> 编辑过再用 git 提交，要确认没被转成 CRLF——CRLF 的 shell 脚本在 Linux 上会报
> `bad interpreter: /bin/bash^M`。测试里有检查，但别依赖它兜底。

---

## 8. 卡住了怎么办

| 现象 | 处理 |
|---|---|
| UU 远程连不上 | 复制粘贴设备 ID `201997749`，不要手打；确认对方虚拟机上 UU 远程在运行 |
| `rocminfo` 无输出 | 可能没装 ROCm。先测 `vulkaninfo`，并**在群里报告** |
| `size_vram == 0` | 模型回退到 CPU 了。查驱动、ROCm 版本、Ollama 日志 |
| `docker` 不存在 | 报告，这是重要环境事实；`Dockerfile` 验证要另想办法 |
| `docker build` 报缺 Vivado | **预期情况**（官方镜像才带 Vivado）。记录报错即可 |
| 显存装不下候选模型 | 记录实际限制。**不能靠跨卡绕过——这是赛题硬约束** |

---

## 9. 参考文档

| 文档 | 用途 |
|---|---|
| `docs/amd-machine-validation-zh.md` | **你的主要参考**，含详细验证流程 |
| `serve/README-zh.md` | `serve/` 设计说明与已验证/未验证对照 |
| `model/MODEL.md` | 你要填的字段（标了 `[待测]`） |
| `docs/status-log-zh.md` | 项目全貌、22 个已修缺陷 |
| `CONTRIBUTING.md` | 协作规范 |
| `REPORT.md` §3、§6 | 模型选择与环境在报告中怎么呈现 |
