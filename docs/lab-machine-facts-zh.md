# 实验室机器环境事实

> **这份文档是实验室环境的权威记录。** 每条都标明来源和可靠程度。
> 后加入的队友**不需要重新勘察**，直接用这份。
>
> ⚠️ **本文档经过两次修订**：初版由队长在 UU 远程下粗略勘察（有几处错误）；
> 第二版依据队友 C 的实测记录修正（`LogicLens-实验室验证交接包-20261011`）。
> **以第二版为准。**

---

## 零、一句话摘要

实验室机器是一台 **Windows 虚拟机**，配备 **AMD Radeon AI PRO R9700（32 GB 专用显存）**，
**Vivado/Vitis 2025.2 已安装**，**Ollama + qwen2.5-coder:7b 能跑在 GPU 上**。
**主要阻塞：Vivado 综合崩溃（`0xC0000374`），疑为本机环境问题。**

---

## 一、基本环境

| 项目 | 值 | 来源 | 可靠度 |
|---|---|---|---|
| 主机名 | `jcsylvm1` | 老师提供 | 🟡 未用命令核验 |
| 设备名 | 虚拟机1 / 「服务器虚拟机1」 | 老师 + C 观察 | ✅ |
| **系统** | **Windows**（OS build 26200） | C 实测 `diag.log` 头部 | ✅ |
| **是虚拟机** | **是** | C：任务管理器显示「虚拟机：是」 | ✅ |
| 远程方式 | 网易 UU 远程（**远程协助模式不支持文件传输**） | C 实测 | ✅ |
| UU 设备 ID | `201997749` | 老师提供 | ✅ |

> ⚠️ **重要修正**：老师最初说的是"linux 环境"，但**实测是 Windows**。
> 最初的操作单和 `task-C-deployment-zh.md` 是按 Linux 写的，**那些命令在这台机器上用不了**。

---

## 二、硬件

| 项目 | 值 | 来源 | 可靠度 |
|---|---|---|---|
| CPU | AMD Ryzen 7 9700X，8 物理核 / 16 逻辑核 | C 实测 | ✅ |
| **内存** | **当前可用 13.7 GB，最大 16.0 GB** | C：任务管理器 | ✅ |
| 内存（补充） | `diag.log` 报 Host memory 17178 MB、Swap 6700 MB、Available Virtual 6079 MB | C 实测 | ✅ |
| **GPU** | **AMD Radeon AI PRO R9700** | C 实测 | ✅ |
| **GPU 专用显存** | **32.0 GB**（任务管理器上报） | C 实测 | ✅ |
| GPU 共享内存 | 45.7 GB | C | ⚠️ **是共享内存，不计入单卡专用显存预算** |
| GPU 驱动版本 | `10.0.26100.1150` | C | ✅ |
| GPU 位置 | **Virtual PCI Bus**（虚拟化设备） | C 观察 | ✅ |
| 是否存在第二张独显 | 列表另有 `AMD Radeon(TM) Graphics`，是**核显**，已排除 | C：Ollama 探测 | ✅ |

### ⚠️ 重要修正：我最初记录的"内存 7.8 GB"是错的

初版记录的内存 7.8 GB **不能代表当前状态**。C 实测为 **13.7 GB 可用 / 16 GB 最大**，
且可能随虚拟机配置变化。

**结论**：**每次正式评测都应重新记录内存**，不要沿用旧值。

### ⚠️ 显卡是 GPU 半虚拟化（`VEN_1414`）

```
AMD Radeon AI PRO R9700    PCI\VEN_1414&DEV_008E&SUBSYS_00000000&REV_00
```

| 厂商 ID | 归属 | 含义 |
|---|---|---|
| `1002` | AMD | 真实物理显卡（直通） |
| **`1414`** | **Microsoft** | **半虚拟化设备（GPU-PV）** |

**这一点的实际影响**（C 已实测，见 §4）：

| 后端 | 结果 |
|---|---|
| **ROCm** | ❌ **不可用**（Ollama 日志：`AMD driver is too old`；`llama-server --list-devices` 以 `0xc0000409` 退出；服务里有 `HSA_OVERRIDE_GFX_VERSION=11.0.0`） |
| **Vulkan** | ✅ **可用**（能发现 R9700，`type=discrete`，`total=31.9 GiB`，`available=31.0 GiB`） |

**所以推理走 Vulkan，不是 ROCm。**

### 磁盘空间

| 盘 | 可用 | 总计 |
|---|---|---|
| **E:** | **328.3 GB** | 512 GB |
| C: | 34.8 GB | 126.9 GB |
| D: | 0 GB | 7.7 GB |
| Z: | 34.8 GB | 126.9 GB |

**结论**：**E 盘是唯一适合放模型和代码的盘。**

---

## 三、软件

| 软件 | 位置 / 版本 | 来源 | 状态 |
|---|---|---|---|
| **Python** | **`E:\python`**，版本 **3.14.8** | 队长实测 | ✅ |
| **Vivado** | **`E:\2025.2\Vivado`**（SW Build 6299465） | 两者 | ✅ 已装（见 §5 崩溃） |
| **Vitis** | `E:\2025.2\Vitis` | 桌面图标 | ✅ 已装 |
| **Ollama** | **`E:\ollama\ollama.exe`**，客户端 0.35.0 | C 实测 | ✅ 已装 |
| **vulkaninfo** | `C:\WINDOWS\system32\vulkaninfo.exe`，Instance 1.4.309 | C 实测 | ✅ |
| **Docker / Podman** | 当前 PATH 未找到 | C | ⚠️ 不能说系统绝对没有 |
| **rocminfo** | 当前 PATH 未找到 | C | ⚠️ 同上 |
| git | 有 | 队长 | ✅ |

取证命令：

```powershell
python --version
Get-ChildItem -Path C:\,D:\,E:\ -Filter "Vivado" -Directory -Depth 2 -ErrorAction SilentlyContinue | Select-Object FullName
Get-Command docker, podman, rocminfo -ErrorAction SilentlyContinue
& 'E:\2025.2\Vivado\bin\vivado.bat' -version
```

### Vivado 使用方式

```powershell
$env:LOGICLENS_VIVADO = "E:\2025.2\Vivado\bin\vivado.bat"
```

> ⚠️ `$env:` 只在**当前 PowerShell 窗口**生效，关掉窗口需重设。

---

## 四、推理服务实测（C 的成果）

### 4.1 模型与显存

| 项目 | 值 | 备注 |
|---|---|---|
| 模型 | `qwen2.5-coder:7b` | |
| 完整摘要 | `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | |
| 参数量 | 7.6B | |
| 格式 / 量化 | GGUF / **Q4_K_M** | |
| 服务版本 | Ollama 0.35.0 | |
| **后端** | **Vulkan**（ROCm 失败） | |
| `on_disk_bytes` | 4,683,087,561（≈ 4.68 GB） | |
| **`size_vram`** | **5,119,263,374 字节（≈ 5.12 GB / 4.77 GiB）** | ⭐ **8192 上下文实测值** |
| `context_length_loaded` | **8192** | 模型最大支持 32768，**不能混为加载值** |
| `gpu_accelerated` | **true** | |
| `ollama ps` | **100% GPU** | |
| 加载耗时 | ≈ 27.46 秒 | |

> ⚠️ **上下文不同，显存值不同，不能混用**：
> - **2048 上下文**：`size` = `size_vram` = 4,621,179,288 字节
> - **8192 上下文**：`size` = `size_vram` = 5,119,263,374 字节 ← **`MODEL.md` 应引用这个**

### 4.2 32B 模型：Vulkan 分配失败（**不代表不支持**）

C 的实测：

```
模型参数 32.76B、65/65 layers offloaded to GPU
CPU_Mapped buffer = 417.66 MiB
Vulkan0 model buffer = 18508.35 MiB
随后申请 79,626,240 字节（≈ 75.94 MiB）失败
vk::Device::allocateMemory: ErrorOutOfDeviceMemory
llama-server 退出码 0xe06d7363，HTTP 500
```

**32B 权重已在磁盘上**（qwen2.5-coder:32b，短 ID `5f0f8c2e8bfc`，19 GB）。

> ⚠️ **不能据此断言"32B 不支持所有 32 GB R9700 环境"。**
> 这是**本次 Vulkan 分配失败**，可能与本机 GPU 半虚拟化有关。

### 4.3 项目 ModelClient 接入检查

C 实测通过：

| 字段 | 值 |
|---|---|
| 端点 | `http://127.0.0.1:11434/v1/chat/completions` |
| `ok` | **true** |
| `reply_preview` | `ready` |
| `elapsed_seconds` | 32.57（含可能的重新加载，不是纯生成性能） |
| 采样配置 | temperature=0.2、top_p=0.95、max_tokens=2048、**seed=null（未固定）** |

> ⚠️ seed 未固定，所以该探测**不能称为正式可复现采样评测**。

### 4.4 服务监听与断网

| 项目 | 值 |
|---|---|
| 监听地址 | **只监听 `127.0.0.1:11434`** |
| cloud disabled | false |
| **断网验收** | ❌ **尚未进行** |

---

## 五、⚠️ 已知故障：Vivado 综合崩溃

### 5.1 现象

| 项目 | 值 |
|---|---|
| 退出码 | **3221226356 = `0xC0000374` = STATUS_HEAP_CORRUPTION（堆损坏）** |
| 是否超时 | **否**（`timed_out=False`） |
| 受影响用例 | `p05_clocked_ok`（71.26 秒崩溃）、`p05_comb_ok`（16.384 秒崩溃） |
| 不受影响 | `p05_clocked_wrong`：编译、展开正常，仿真正确判为失败 ✅ |

### 5.2 崩溃位置固定

```
INFO: [Synth 8-7079] Multithreading enabled for synth_design using a maximum of 2 processes.
INFO: [Synth 8-7078] Launching helper process for spawning children vivado processes
INFO: [Synth 8-7075] Helper process launched with PID 4396
INFO: [Synth 8-6155] done synthesizing module 'counter'      ← 最后一行，进程消失
```

**两次都崩在"综合完第一个模块、helper 刚启动"之后。**

### 5.3 ⭐ 关键对照：同一版本在开发机上综合成功

| 对比项 | 实验室机器 | 开发机（队长） |
|---|---|---|
| Vivado | 2025.2，**SW Build 6299465** | **完全相同** |
| 目标器件 | `xczu3eg-sbva484-1-e` | **完全相同** |
| 被测电路 | `counter`、`alu_comb` | **相同** |
| TCL 流程 | `vivado/run_flow.tcl` | **同一份文件** |
| **结果** | 🔴 崩溃 | ✅ **成功，`synthesis_pass=1`，110 秒** |

**成功日志的完整尾部**（开发机 `experiments/runs/.../vivado.log`）：

```
INFO: [Synth 8-6157] synthesizing module 'TopModule'
INFO: [Synth 8-6155] done synthesizing module 'TopModule' (0#1)
WARNING: [Synth 8-3330] design TopModule has an empty top module
INFO: [Synth 8-6742] Reading net delay rules and data               ← ★ 崩溃那台没有这一行
Synthesis finished with 0 errors, 0 critical warnings and 4 warnings.
13 Infos, 4 Warnings, 0 Critical Warnings and 0 Errors encountered.
synth_design completed successfully
synth_design: Time (s): cpu = 00:00:17 ; elapsed = 00:00:27 . Memory (MB): peak = 2220.332
```

**对照结论**：崩溃那台**停在 `done synthesizing module`**，
**缺少从 `Reading net delay rules and data` 开始的全部后续阶段**。

**这一个对照排除了四种可能**：

| 排除的假设 | 依据 |
|---|---|
| ❌ 我们的 TCL 流程有 bug | 同一份脚本另一边成功 |
| ❌ 目标器件不支持 | 同一器件成功 |
| ❌ 缺 Synthesis 许可证 | 两边日志都明确 `Got license for feature 'Synthesis'` |
| ❌ 内存不足 | **成功那台峰值仅 2220 MB / 崩溃那台 1764 MB**，而机器有 13.7 GB 可用 |

**结论：这是实验室那台机器的环境问题，不是我们的代码问题。**

### 5.3.1 GUI 对照测试（C 于 2026-10-12 完成）

**这项测试排除的变量很重要：它证明崩溃不是我们的 Python 调用方式造成的。**

C 用 **Vivado 图形界面**（新建工程向导 + GUI 按钮，**完全没用终端或 Tcl**）跑同一个最小案例：

| 项目 | 结果 |
|---|---|
| 工程 | `E:\LogicLens_GUI_20261012_0811` |
| 器件 / 顶层 | `xczu3eg-sbva484-1-e` / `alu_comb` |
| **行为仿真** | ✅ **通过**：`TEST_PASS`、`$finish called at time: 2 ns`、`XSIM Completed` |
| **综合** | 🔴 **失败**：`Synthesis Failed`，`synth_1` 状态 `synth_design ERROR` |
| 日志位置 | `...\LogicLens_GUI_20261012_0811.runs\synth_1\runme.log` |
| 日志尾部 | **同样停在 `done synthesizing module`**，`maximum of 2 processes`、`helper PID 14876` |
| GUI 默认 jobs | 对话框显示 `Number of jobs=8`（**与后台 `general.maxThreads` 不等同**） |

**这项测试的价值**：

| 证明了什么 | 说明 |
|---|---|
| ✅ **不是我们的 Python/批处理调用方式的问题** | GUI 模式同样崩溃 |
| ✅ **仿真链路在 GUI 下也正常** | 进一步确认编译/仿真可用 |
| ⚠️ 仍是"对照诊断，不是完全单变量实验" | GUI/项目模式与批处理存在运行配置差异（C 自己指出，很准确） |

**C 未取得子进程退出码**，所以**不能声称已确认是同一个 `0xC0000374`**（他如实标注了这一点）。

**待读的证据**：运行目录里的 **`.vivado.error.rst`**（C 观察到但未读内容），可能包含更具体的失败信息。

### 5.4 两个待查方向

| 方向 | 依据 | 状态 |
|---|---|---|
| **① AMD 图形驱动干扰** | Ollama 日志明确 `AMD driver is too old`（`25.20.42.14 (LLPC)`）。图形驱动 DLL 会加载进**每一个**用户态进程，在 GPU 半虚拟化 + 旧驱动下与堆管理冲突是 `0xC0000374` 的经典成因 | ❓ 待验证（查事件日志 `Faulting module name`） |
| **② 综合 helper 多进程** | 崩溃点固定在 `Launching helper process` 之后，默认开 2 个进程 | ❓ 待验证 |

> ⚠️ C 试过的 `set_param general.maxThreads 1` **可能没有限制 helper 的子进程数**——
> 那个参数控制综合算法内部线程，helper 是独立的派生进程机制。**方向 ② 还没被真正测过。**

### 5.5 原始证据位置（未收入交接包）

| 内容 | 路径 |
|---|---|
| Vivado 最小复现目录 | `E:\LLdiag_20261011_150316`（含 `alu_comb.v`、`diag.log`、`diag.jou`） |
| 模型探测证据 | `experiments\results\gpu_probe_20261011_145747\`（`ps.json`、`tags.json`、`server-tail.log`、`model-client-check.json`、`service-measurements-7b.json`） |

---

## 六、网络

| 目标 | 结果 | 来源 |
|---|---|---|
| **`codeload.github.com`** | ✅ **可访问** | C 实测（用浏览器下载了 zip） |
| `github.com` 主站 | ❌ `git clone` 超时 | 队长实测 |
| `ollama.com:443` | ✅ 可达 | 队长实测 |
| 本地代理 | ❓ 未测试 | — |

> ⚠️ **修正**：我最初结论"GitHub 不可达，代码必须用 zip 传"**过于绝对**。
> **`codeload.github.com` 可达**，可以直接下载仓库 zip：
> `https://codeload.github.com/lsxzcd/LogicLens/zip/refs/heads/main`

---

## 七、当前状态：哪些已验证、哪些没有

### 7.1 已在实验室机器上验证 ✅

| 项目 | 结果 | 来源 |
|---|---|---|
| 代码移植 | ✅ 成功（codeload zip 下载解压） | C |
| **124 个单元测试** | ✅ **全部通过**（9.127 秒） | C |
| 架构守卫 | ✅ 通过 | C |
| 接口解析检查 | ✅ 7 题，0 unexplained | C |
| 编译 + 仿真（反例） | ✅ 正确判错 | C |
| Ollama + Vulkan + R9700 | ✅ 100% GPU | C |
| 7B 模型显存占用 | ✅ `size_vram` = 5.12 GB @ 8192 上下文 | C |
| 项目 ModelClient 接入 | ✅ `ok=True` | C |

### 7.2 未完成 ❌

| 项目 | 原因 |
|---|---|
| **Vivado 综合（C1）** | 🔴 崩溃，根因未定 |
| **C2 断网容器验收** | 未装 Docker |
| **C3 正式模型质量评测** | 未做 |
| **全量 156 题评测** | 未做 |
| 安装权限确认 | 未确认 |

> **C 的结论（我同意）**：**不能宣称全链路或正式性能验收通过。**

---

## 八、待确认事项

| # | 问题 | 影响 | 该问谁 |
|---|---|---|---|
| 1 | **这台机器允许安装软件吗？** | 决定模型服务部署方式 | 老师 |
| 2 | **最终评测在哪台机器上？** | 决定为哪个环境适配 | 老师 / 赛事方 |
| 3 | **评测环境是容器吗？** | 决定 `Dockerfile` 严格程度 | 赛事方 |
| 4 | **Vivado 综合崩溃是否其他机器也有？** | 是否环境特有问题 | 老师协调另一台机器 |
| 5 | **是否有本地代理？** | 能否访问 GitHub 主站 | 老师 |
| 6 | 主机名等未用命令核验的项目 | 文档准确性 | 下次远控时补 |

---

## 九、修订记录

| 版本 | 时间 | 变更 |
|---|---|---|
| 初版 | 队长勘察 | 记录 Windows 系统、R9700（VEN_1414）、内存 7.8 GB、E 盘 328 GB、Python 3.14.8 @E:\python、Vivado @E:\2025.2\Vivado、无 Docker、GitHub 不可达 |
| **第二版** | 依 C 的交接包修正 | **内存改为 13.7 GB / 16 GB 最大**；**GitHub 改为 codeload 可达**；补充 Vulkan 可用 / ROCm 不可用；补充 7B 实测显存；**新增 §5 Vivado 综合崩溃分析（含开发机对照）**；补充 Ollama @E:\ollama、vulkaninfo 路径 |
