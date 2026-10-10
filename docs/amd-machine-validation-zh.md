# 在 AMD 显卡机器上的验证方案

学校提供的 AMD 显卡机器到位后，按本文执行。目标是**零代码改动**完成验证——所有模型相关配置都在环境变量里，换机器不需要改代码。

---

## 0.1 实验室验证环境（已确认）

由实验室老师提供，通过**网易 UU 远程**访问：

| 项目 | 值 |
|---|---|
| 设备名称 | 虚拟机1 |
| **UU 远程设备 ID** | **201997749** |
| 主机名 | `jcsylvm1` |
| 远程方式 | 网易 UU 远程 → 远程协助 → 填「伙伴的设备ID」 |
| **环境类型** | **Linux 虚拟机**（老师原话："linux 环境"） |

### 访问步骤

1. 打开 UU 远程 → 左侧 **远程协助**
2. 在「伙伴的设备ID」填入 **`201997749`**（**建议从聊天记录复制粘贴，不要手打**——曾因把 ID 输成 `120199774` 而报"设备ID错误或不存在"）
3. 点「连接」

### ⚠️ 这条信息很重要

环境是 **Linux 虚拟机**，这消除了本项目一个已知限制：

| 之前 | 现在 |
|---|---|
| `serve/*.sh` 只能在 Windows 上写、**无法验证** | ✅ Linux 下可**原生运行并验证** |
| `Dockerfile`（基于 ubuntu）未验证 | ✅ 可在该机器上**真实构建** |
| 报告 §10.2「未验证实现」多条 | ✅ 有机会**逐条消掉** |

**验证优先级**：连上后先跑 `serve/` 脚本和 `Dockerfile` 构建，
把报告里"未验证"的条目变成已测，这比先跑模型评测更划算——
因为脚本跑通了，模型评测才有可靠载体。

### 注意主控/被控关系

UU 远程有两套机制，容易混淆：

| 机制 | 作用 |
|---|---|
| 「允许他人远程协助」开关 | 决定**是否接受**他人协助 |
| 临时验证码 | 每次远程结束刷新，用于**别人连你** |

**我们是主控**（连过去），所以需要**对方**虚拟机上的「允许他人远程协助」打开且 UU 远程在运行。

---

## 0.2 当前软件完成度（先读）

在这台开发机（Intel 核显）上已经完成并验证：

| 项目 | 状态 | 证据 |
|---|---|---|
| 三级判定（编译→仿真→综合） | ✅ 目标器件实测 | `experiments/p05_verify.py` → `0 failed, 0 env-blocked` |
| VerilogEval 官方 testbench | ✅ xsim 实测 | `experiments/verilogeval_verify.py` → 双向验证通过 |
| 156 道题接口解析 | ✅ 153 正确、0 无法解释 | `tools/check_parsing.py` |
| 模型接入链路 | ✅ 端到端验证 | `experiments/model_e2e_verify.py` |
| 单元测试 | ✅ 84 个全绿 | CI 三版本 Python |

**在 AMD 机器上需要补的只有两件**：

1. **真实模型推理**（本机只有核显，跑不动）
2. **赛题要求的显存验证**（模型须装入单卡 32 GB）

---

## 1. AMD 机器环境准备

### 1.1 检查显卡与驱动

```powershell
# 显卡型号
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion

# ROCm 是否可用（装好 AMD 驱动后）
& "C:\Program Files\AMD\ROCm\*\bin\rocminfo.exe" 2>$null | Select-String "Name:|gfx"
```

**关键**：Ollama 需要 **ROCm v7 / HIP7 驱动栈**，或 **Vulkan** 作为回退。
题集指南提到 RDNA2/RX 6000 系列在某些驱动下不暴露 ROCm，此时用 Vulkan。

### 1.2 拿到项目代码

```powershell
git clone https://github.com/lsxzcd/LogicLens.git
cd LogicLens
git log --oneline -1        # 确认是最新
```

### 1.3 装 Python 依赖

项目**只用 Python 标准库**，装 Python 3.11+ 即可，无需 pip install。

### 1.4 装 Vivado 2025.2 + 目标器件

**必须含 `xczu3eg-sbva484-1-e`**。装完确认：

```powershell
py -3 -c "from agent.vivado_runner import locate_vivado; print(locate_vivado(None))"
# 应输出 vivado.bat 的路径；为 None 就设 LOGICLENS_VIVADO
```

### 1.5 装 Ollama 并把模型放到大容量盘

```powershell
# 安装到非系统盘（C 盘空间通常紧张）
OllamaSetup.exe /DIR="D:\JZDSLx\ollama_location"

# 模型也放非系统盘
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\JZDSLx\ollama_models", "User")
```

---

## 2. 模型选型（按显存决定）

赛题约束：**单卡 32 GB 内完整容纳，不允许跨卡**。以下按显存选：

| 显存 | 推荐模型 | 量化 | 显存占用（估） |
|---|---|---|---|
| 32 GB | `deepseek-coder-v2:16b` | Q4_K_M | ~11 GB |
| 32 GB | `qwen2.5-coder:32b` | Q4_K_M | ~20 GB |
| 48 GB（W7900） | 32B 级 | Q6/Q8 | ~27~35 GB |

**选型原则**（写进 `MODEL.md`）：

1. 必须**开源权重**且声明来源与版本号
2. 必须能**单卡容纳**——这是硬约束，超了就不能用
3. 先跑 7B~16B 级别把数据跑通，再上更大模型比增益

拉取模型：

```powershell
ollama pull qwen2.5-coder:32b
ollama list
```

**实测显存占用**（必须记录进 `MODEL.md`）：

```powershell
# 推理时另开一个窗口观察
nvidia-smi          # 若为 NVIDIA
# AMD 用:
& "C:\Program Files\AMD\ROCm\*\bin\rocm-smi.exe" --showmeminfo vram
```

或直接用 Ollama 的日志确认是否走了 GPU：

```powershell
Get-Content "$env:LOCALAPPDATA\Ollama\server.log" -Tail 40 | Select-String "library|ROCm|Vulkan|CPU"
# 看到 ROCm 或 Vulkan 说明走了 GPU；只有 CPU 说明回退到 CPU 了
```

---

## 3. 三步验证（按顺序，每步都必须过）

### 第 1 步：环境自检（不需要模型）

```powershell
cd LogicLens
py -3 -m unittest discover -s tests          # 期望 84 个全绿
py -3 tools/check_architecture.py            # 期望无硬编码
py -3 tools/check_parsing.py                 # 期望 0 unexplained
```

### 第 2 步：三级判定（需要 Vivado，约 3 分钟）

```powershell
py -3 experiments\p05_verify.py
# 期望：3 cases, 0 failed assertion(s), 0 env-blocked
```

⚠️ **如果出现 `env-blocked`**，说明 Vivado 的 Tcl app store 有问题（我们在沙箱里遇到过），
把 `synthesis_error` 字段的内容发出来排查。

### 第 3 步：真实模型端到端（需要模型服务）

```powershell
$env:LOGICLENS_MODEL_URL  = "http://127.0.0.1:11434/v1"
$env:LOGICLENS_MODEL_NAME = "qwen2.5-coder:32b"
$env:LOGICLENS_SEED       = "1"        # 固定种子，保证可复现
py -3 tools\check_model.py              # 期望 OK replied in ...s
```

端点通过后，先小规模跑：

```powershell
py -3 eval.py --dataset experiments\data\verilogeval --mode both --limit 5 --samples 1
```

**看三件事**：
1. `pass@1` 是否非 0（模型能否真的写出通过官方 testbench 的代码）
2. `error_types` 分布（失败集中在哪类）
3. `mean_elapsed_seconds`（决定全量跑得完跑不完）

再全量：

```powershell
py -3 eval.py --dataset experiments\data\verilogeval --mode both --samples 5 --out experiments\results\final
```

> ⏱️ **时间预算**：单题约 85 秒（其中综合占 85%）。156 题 × 5 采样 × 2 模式 ≈ 37 小时机器时间。
> **必须**先用 `--limit` 验证，并考虑并行跑多份（注意显存和 CPU 争用）。

---

## 4. 需要产出的结果

`eval.py` 会写出：

| 文件 | 内容 |
|---|---|
| `results.csv` | 每题每次采样的全部判定字段，可审计 |
| `summary.json` | 各级通过率、pass@1..pass@k、错误类型分布、耗时 |
| `gain.md` | Baseline vs LogicLens 对比表 + 增益幅度 |

**回填到 `REPORT.md` 第 7 节**，并在 `MODEL.md` 记录：

- 模型仓库地址 + 版本号/权重校验和
- 量化方式
- **实测显存占用**
- 上下文长度与最大输出长度
- 是否微调

⚠️ **红线**：`--mock` 的结果**禁止**写入报告结论（赛题要求真实可复现）。

---

## 5. 常见问题

| 现象 | 处理 |
|---|---|
| `tools/check_model.py` 报连接被拒 | Ollama 服务没起 → 启动 Ollama 应用，或 `ollama serve` |
| 模型跑了但很慢 | 检查 `server.log` 是否回退到 CPU；AMD 需 ROCm/Vulkan 驱动 |
| `locate_vivado` 返回 None | 设 `LOGICLENS_VIVADO` 或用 `--vivado` 指定 |
| 综合报 `tclapp::load_apps` | Vivado 安装/授权异常，不是设计问题；重启 Vivado 或检查 license |
| 显存不足（模型装不下） | 换更小量化或更小模型——这是赛题硬约束，不能靠跨卡绕过 |
| 结果不稳定、pass@k 波动大 | 设 `LOGICLENS_SEED` 固定种子；确认 `run.sh` 与 `run_baseline.sh` 采样配置一致 |

---

## 6. 提交物清单（赛题 3.1.5）

| 提交项 | 状态 | 位置 |
|---|---|---|
| `Dockerfile`（基于官方基础镜像） | ❌ 未做 | 根目录 |
| `model/MODEL.md` | ⚠️ 模板已有，待填实测数据 | `model/MODEL.md` |
| `agent/` 智能体源码 | ✅ | `agent/` |
| `skill/` 技能包 | ⚠️ 雏形，需扩充 | `skill/` |
| `serve/` 推理服务配置 | ❌ 未做 | 根目录 |
| `run.sh` | ✅ | 根目录 |
| `run_baseline.sh` | ✅ | 根目录 |
| `REPORT.md` | ⚠️ 骨架已有，待填实验数据 | `REPORT.md` |

**断网沙箱要求**：容器必须能**离线**完成从读题到出码。这需要：
- 模型权重打进镜像（或随镜像挂载）
- 不依赖任何网络调用
- 全部路径用相对路径或环境变量
