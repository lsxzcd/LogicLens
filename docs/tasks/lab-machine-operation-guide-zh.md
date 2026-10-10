# 远控实验室机器 · 操作单

> **用法**：远控连上后，**打开一个终端**，从第 0 步开始**按顺序复制粘贴**每条命令。
> 每步都写了**预期输出**和**异常怎么办**。
>
> ⚠️ 关键：**第 1 步的输出必须复制回来**。那是决定模型选型的唯一依据。

---

## 使用前必读

### 怎么把结果给我

远控机器上的输出你**复制不回来**（剪贴板不互通）。所以有两种办法：

| 办法 | 做法 |
|---|---|
| **A. 拍照/截图** | 用手机拍屏幕，发给我 |
| **B. 存成文件再传** | 如果远控支持文件传输，把输出存成文件传出来 |

**推荐 A**，快。**第 1 步的输出务必发我。**

### 一个原则：不要猜，不要慌

- 命令报错很正常（软件没装、权限不够），**把报错原样发我**，不要自己想办法绕过
- **不要**在没有确认的情况下装 Vivado（几十 GB，且官方镜像里本来就有）
- **不要**改动仓库里的代码——先勘察，再动手

---

## 第 0 步：确认你在哪台机器上（30 秒）

```bash
hostname
whoami
uname -a
pwd
```

**预期**：`hostname` 应该显示 `jcsylvm1`。

**如果不是 `jcsylvm1`**，说明连错机器了，**停下来告诉我**。

**这条命令的意义**：确认后面所有操作都作用在正确的机器上。

---

## 第 1 步：环境勘察 ⭐ **最重要，输出务必发我**

这一步只读不写，很安全。**建议一条一条跑**，每条的输出都留着。

### 1.1 显卡型号

```bash
lspci | grep -i -E "vga|display|3d"
```

**预期**：能看到 `Advanced Micro Devices` 或 `AMD/ATI` 的字样，例如：

```
01:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31 ...
```

**如果只看到 `Intel` 或 `VMware`/`Red Hat` 虚拟显卡** → 说明显卡没直通给虚拟机，**这是重大发现，立刻告诉我**。

### 1.2 显存容量 ⭐ 这是选模型的依据

```bash
rocm-smi --showmeminfo vram 2>/dev/null || rocm-smi 2>/dev/null || echo "ROCM_SMI_NOT_AVAILABLE"
```

**预期**：看到类似

```
GPU[0] : VRAM Total Memory (B): 51522882560
```

**要记录的数字**：VRAM 总量（字节）。换算参考：
- 约 51,522,882,560 字节 ≈ **48 GB**
- 约 34,359,738,368 字节 ≈ **32 GB**
- 约 17,179,869,184 字节 ≈ **16 GB**
- 约 8,589,934,592 字节 ≈ **8 GB**

**如果显示 `ROCM_SMI_NOT_AVAILABLE`** → 不要紧，继续下一步，我们用别的方式查。

### 1.3 ROCm 与显卡架构

```bash
rocminfo 2>/dev/null | head -50 || echo "ROCMINFO_NOT_AVAILABLE"
```

**预期**：能看到 `Name: gfx1030` 或 `gfx1100` 之类的架构代号，以及 `Marketing Name` 里的显卡型号。

**要记录**：`gfx` 代号 + 显卡型号。

> **为什么重要**：赛题指南提到 **RDNA2 / RX 6000 系列**在某些驱动下不暴露 ROCm v7，
> 这时要走 **Vulkan 回退**。`gfx10xx` 一般是 RDNA2，`gfx11xx` 是 RDNA3。

### 1.4 Vulkan 是否可用（ROCm 不行时的替代方案）

```bash
vulkaninfo 2>/dev/null | head -30 || ls /usr/share/vulkan/icd.d/ 2>/dev/null || echo "VULKAN_NOT_AVAILABLE"
```

**预期**：能看到显卡信息，或者 `/usr/share/vulkan/icd.d/` 下有 `radeon_icd.x86_64.json` 之类。
**记录**：Vulkan 可用 = 是 / 否

### 1.5 显卡驱动

```bash
cat /sys/module/amdgpu/version 2>/dev/null || echo "AMdGPU_MODULE_NOT_LOADED"
dkms status 2>/dev/null | head -5
```

### 1.6 Vivado / Vitis 工具链

```bash
which vivado xvlog xelab xsim vitis 2>/dev/null || echo "NOT_IN_PATH"
```

**预期**：如果装了，会列出路径。

**如果显示 `NOT_IN_PATH`**，再试试常见安装位置：

```bash
ls -d /opt/Xilinx /tools/Xilinx /opt/amd 2>/dev/null
ls -d /opt/Xilinx/Vivado/* 2>/dev/null
```

**记录**：Vivado 版本与路径（或"未安装"）

### 1.7 目标器件是否可用

这是**赛题指定的器件**，必须确认存在：

```bash
vivado -version 2>/dev/null | head -3
```

**记录**：Vivado 版本号。器件确认要等装好 Vivado 后跑流程时才能验，先记版本。

### 1.8 容器环境

```bash
which docker podman 2>/dev/null || echo "NO_CONTAINER_RUNTIME"
docker --version 2>/dev/null
docker info 2>/dev/null | head -5
```

**记录**：Docker 可用 = 是 / 否

> **如果没装 Docker**：这是重要信息。我们的 `Dockerfile` 就没法在这台机器上验证。

### 1.9 系统资源（决定评测能不能并行）

```bash
nproc
free -g | head -2
df -h / /home /opt 2>/dev/null
```

**记录**：
- CPU 核数（`nproc`）
- 内存 GB
- **磁盘可用空间**（模型要几 GB ~ 几十 GB，注意看哪个分区大）

### 1.10 网络（判断能不能装东西）

```bash
timeout 8 curl -sI https://ollama.com 2>&1 | head -3 || echo "NO_NETWORK_TO_OLLAMA"
timeout 8 curl -sI https://github.com 2>&1 | head -3 || echo "NO_NETWORK_TO_GITHUB"
```

**记录**：外网通不通。

---

## 📋 第 1 步结果汇总（照这个格式发我）

把下面的模板复制到一个文本文件里，填好**发我**：

```
=== 实验室机器环境勘察 ===
hostname        ：
显卡型号        ：
显存总量        ：
gfx 架构        ：
ROCm 版本       ：
Vulkan 可用     ：是 / 否
Vivado 版本     ：
Vivado 路径     ：
Docker 可用     ：是 / 否
Python 版本     ：
CPU 核数        ：
内存            ：
磁盘可用        ：
外网可达        ：是 / 否
```

**Python 版本**顺手跑一下：`python3 --version`

---

## 第 2 步：拿到我们的代码

⚠️ **在跑这一步之前，先把第 1 步的汇总发我**，因为后面怎么做取决于勘察结果。

```bash
cd ~
git clone https://github.com/lsxzcd/LogicLens.git
cd LogicLens
git log --oneline -1
```

**预期**：克隆成功，`git log` 显示一个提交哈希。

**如果没装 git**：

```bash
sudo apt update && sudo apt install -y git     # Debian/Ubuntu
# 或
sudo dnf install -y git                          # RHEL/CentOS/Fedora
```

### 2.1 三项自检（**必须全过**）

```bash
python3 -m unittest discover -s tests
```

**预期**：

```
Ran 124 tests in 9.1s

OK
```

⚠️ **如果不是 `OK`，截图发我，不要继续。**

```bash
python3 tools/check_architecture.py
```

**预期**：`architecture guard: no hardcoded testbench path in agent/`

```bash
python3 tools/check_parsing.py
```

**预期**：`===== 7 task(s), ... 0 unexplained =====`（干净克隆只有 7 道题）

---

## 第 3 步：看 Vivado 能不能真的跑（**这一步很关键**）

三级判定是赛题核心。先确认工具链在这台机器上真的能用。

```bash
cd ~/LogicLens
python3 experiments/p05_verify.py
```

**预期**：

```
===== 3 cases, 0 failed assertion(s), 0 env-blocked =====
```

**三种可能的异常，对应不同处理**：

| 输出 | 含义 | 怎么办 |
|---|---|---|
| `env-blocked` > 0 | Vivado 的 `tclapp::load_apps` 失败（我们在沙箱里遇到过） | 截图发我，记录 `synthesis_error` 字段内容 |
| `locate_vivado` 返回 None | Vivado 路径没找到 | 设 `export LOGICLENS_VIVADO=/你的/vivado/bin/vivado` |
| `Vivado not found` | 没装 Vivado | **先别装**（几十 GB），告诉我 |

⏱️ **这步约 3 分钟**（要跑综合）。

---

## 第 4 步：装推理服务

⚠️ **这一步取决于第 1 步的结果**：
- 如果实验室机器**已经有模型服务**（比如老师在跑）→ **先告诉我**，可能不用自己装
- 如果没有 → 按下面做

### 4.1 装 Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

**预期**：显示版本号，如 `ollama version is 0.x.x`

**如果网络不通** → 告诉我，我们想别的办法。

### 4.2 把模型目录放到大分区

**先看哪个分区大**（第 1.9 步的结果）：

```bash
df -h | sort -k4 -h -r | head -5
```

然后设置模型目录（**换成你实际的大分区路径**）：

```bash
export OLLAMA_MODELS=/你选的大分区路径/ollama_models
mkdir -p "$OLLAMA_MODELS"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
```

> **为什么要改**：模型有几 GB 到几十 GB，默认放 `~/.ollama`，可能把系统盘撑满。

**让它永久生效**（可选，但推荐）：

```bash
echo "export OLLAMA_MODELS=$OLLAMA_MODELS" >> ~/.bashrc
```

### 4.3 拉取模型

⚠️ **拉哪个模型取决于显存**——所以这一步**等我根据第 1 步结果给你型号再拉**。

先拉一个小模型验证链路（约 1 GB，任何显存都装得下）：

```bash
ollama pull qwen2.5-coder:1.5b
ollama list
```

### 4.4 启动并验证

```bash
ollama serve &
sleep 10
curl -s http://127.0.0.1:11434/api/version
```

**预期**：返回 `{"version":"0.x.x"}`

### 4.5 ⭐ 记录**实测显存占用**（`MODEL.md` 的核心数据）

```bash
cd ~/LogicLens
python3 serve/record_service.py --model qwen2.5-coder:1.5b --json
```

**重点看 `size_vram` 字段**：

| 值 | 含义 | 处理 |
|---|---|---|
| `size_vram > 0` | ✅ 模型已驻留显存，**这就是实测显存占用** | 记下来，写进 `MODEL.md` |
| `size_vram == 0` | ❌ 回退到 CPU 了 | 截图发我，要查 ROCm 驱动 |

**这个字段是赛题"单卡 32 GB"硬约束的唯一证据。** 务必发我。

---

## 第 5 步：拿模型真跑一道题（验证完整链路）

```bash
cd ~/LogicLens
export LOGICLENS_MODEL_URL="http://127.0.0.1:11434/v1"
export LOGICLENS_MODEL_NAME="qwen2.5-coder:1.5b"
export LOGICLENS_SEED=1

python3 run.py --question experiments/data/verilogeval/examples/Prob001_zero_prompt.txt
```

**预期**：打印一大段 JSON，最后几行关键字段：

```
"compile_pass": 1,
"simulation_pass": 1,     ← 这个可能是 0，取决于模型能力
"synthesis_attempted": 1,
"synthesis_pass": 1,      ← 关键！综合真的跑通了
```

**这一步验证的是**：题目 → 模型 → 代码 → 官方 testbench → xsim 判定 → 综合，**整条链路**。

⏱️ 约 1 分钟。

---

## 第 6 步：验证容器（如果 Docker 可用）

**只有第 1.8 步显示 Docker 可用时才做。**

```bash
cd ~/LogicLens
docker build --build-arg BASE_IMAGE=ubuntu:24.04 -t logiclens .
```

**可能的结果**：

| 结果 | 含义 |
|---|---|
| 构建成功 | ✅ 结构合理 |
| 报错缺 Vivado | **预期情况**（官方镜像才带 Vivado），记录报错即可 |
| 报错缺别的依赖 | 发我，可能是 `Dockerfile` 要改 |

然后测断网（赛题硬要求）：

```bash
docker run --rm --network none -v "$OLLAMA_MODELS":/models logiclens --check
```

**预期**：容器在**无网络**下完成自检。

---

## 到这一步为止，请发我的东西

按优先级：

| 优先级 | 内容 |
|---|---|
| **P0** | 第 1 步的环境勘察汇总表 |
| **P0** | 第 4.5 步的 `size_vram` 值 |
| P1 | 第 3 步 `p05_verify.py` 的输出 |
| P1 | 第 5 步的 JSON 结果 |
| P2 | 第 6 步的容器构建结果 |

**拿到 P0 两项，我就能定模型选型，然后指导你跑全量评测。**

---

## 常见问题速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `command not found: rocm-smi` | 没装 ROCm | 继续用 `lspci` 看显卡；告诉我 |
| `size_vram == 0` | 模型跑在 CPU 上 | 查驱动 / ROCm 版本；发我 |
| `Permission denied` | 权限不足 | 命令前加 `sudo`，或告诉我 |
| `git clone` 卡住/失败 | 网络问题 | 发我，可能需要代理 |
| Vivado 找不到 | 路径没在 PATH | 设 `LOGICLENS_VIVADO` 环境变量 |
| `p05_verify.py` 报 env-blocked | Tcl app store 问题 | 发我 `synthesis_error` 内容 |
| 磁盘满了 | 模型太大 | 换大分区，改 `OLLAMA_MODELS` |
| 显存装不下模型 | 显存 < 模型需求 | **记录实际限制**，不能靠跨卡绕过（赛题硬约束） |

---

## 三条**不要做**的事

1. **不要装 Vivado**——几十 GB，而且官方评测镜像里本来就带。除非第 3 步确认没装，且我们讨论过。
2. **不要修改仓库代码**——先勘察，把情况发我，我们讨论后再改。
3. **不要在没有确认显存前拉大模型**——可能把磁盘撑满。

---

## 一句话总结

**先跑第 1 步，把汇总表发我。** 后面怎么走取决于那张表。
