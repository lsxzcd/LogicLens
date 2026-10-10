# 实验室机器环境事实（已勘察）

> 这些是**实测得到**的事实，不是推测。每条都附了取证命令。
> 后加入的队友**不需要重新勘察**，直接用这份文档。
>
> 勘察日期：见文末修订记录。勘察方式：网易 UU 远程。

---

## 一、基本环境

| 项目 | 值 | 取证命令 |
|---|---|---|
| 主机名 | `jcsylvm1` | `hostname` |
| 设备名 | 虚拟机1 | 老师提供 |
| **系统** | **Windows**（版本 10.0.26200.9457） | `cmd /c ver` |
| **系统类型** | ⚠️ **虚拟机**（存在 `Microsoft Hyper-V 视频` 显示适配器） | `Get-CimInstance Win32_VideoController` |
| 远程方式 | 网易 UU 远程 | — |
| UU 设备 ID | `201997749` | 老师提供 |

> ⚠️ **注意**：老师最初说的是"linux 环境"，但**实测是 Windows**。
> 本项目的 `serve/*.sh` 是 bash 脚本，在 Windows 上**不能直接运行**（见 §5）。

---

## 二、硬件

| 项目 | 值 | 评价 |
|---|---|---|
| CPU | AMD Ryzen 7 9700X（8 核 16 线程） | ✅ 很强 |
| **内存** | **7.8 GB** | ⚠️ **最紧张的资源** |
| GPU | **AMD Radeon AI PRO R9700** | ✅ 型号符合赛题要求 |

取证命令：

```powershell
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, PNPDeviceID
```

### ⚠️ 显卡的一个技术风险：厂商 ID 是 `1414`，不是 AMD 的 `1002`

```
AMD Radeon AI PRO R9700    PCI\VEN_1414&DEV_008E&SUBSYS_00000000&REV_00
```

| 厂商 ID | 归属 | 含义 |
|---|---|---|
| `1002` | AMD | 真实物理显卡（直通） |
| **`1414`** | **Microsoft** | **半虚拟化设备（GPU-PV）** |

**推论**：这张卡是通过 Hyper-V 的 GPU 半虚拟化给到虚拟机的，**不是物理直通**。

**影响**：**ROCm 可能无法使用**（ROCm 需要直接访问物理 GPU）。
Ollama 在 Windows 上有 **Vulkan 后端**作为回退，Vulkan 对 GPU-PV 的支持通常更好。

**状态**：❓ **未实测**。需要用 `ollama ps` 看 `PROCESSOR` 列才能确定（见 §5）。

### 磁盘空间

| 盘 | 可用 | 总计 |
|---|---|---|
| **E:** | **328.3 GB** | 512 GB |
| C: | 34.8 GB | 126.9 GB |
| D: | 0 GB | 7.7 GB |
| Z: | 34.8 GB | 126.9 GB |

取证命令：

```powershell
Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}, @{n='TotalGB';e={[math]::Round(($_.Free+$_.Used)/1GB,1)}}
```

**结论**：**E 盘是唯一适合放模型和代码的盘**（328 GB）。

---

## 三、软件

| 软件 | 位置/版本 | 状态 |
|---|---|---|
| **Python** | **`E:\python`**，版本 **3.14.8** | ✅ 满足 3.11+ 要求 |
| **Vivado** | **`E:\2025.2\Vivado`** | ✅ **已安装** |
| **Vitis** | `E:\2025.2\Vitis`（桌面有图标） | ✅ 已安装 |
| Vitis Model Composer | 桌面有图标 | 未核实 |
| **Docker** | — | ❌ **未安装** |
| git | 有（但 GitHub 连不上） | ⚠️ |

取证命令：

```powershell
python --version
Get-ChildItem -Path C:\,D:\,E:\ -Filter "Vivado" -Directory -Depth 2 -ErrorAction SilentlyContinue | Select-Object FullName
Get-ChildItem -Path C:\,D:\,E:\ -Filter "Vitis" -Directory -Depth 2 -ErrorAction SilentlyContinue | Select-Object FullName
Get-Command docker -ErrorAction SilentlyContinue
```

### Vivado 路径（重要）

```
E:\2025.2\Vivado
```

所以对应可执行文件应为 `E:\2025.2\Vivado\bin\vivado.bat`。

**使用方式**（Windows PowerShell）：

```powershell
$env:LOGICLENS_VIVADO = "E:\2025.2\Vivado\bin\vivado.bat"
```

> ⚠️ `$env:` 只在**当前窗口**生效，关掉窗口需重设。

---

## 四、网络

| 目标 | 结果 |
|---|---|
| `ollama.com:443` | ✅ **可达**（`Test-NetConnection` 返回 True） |
| **`github.com:443`** | ❌ **不可达**（`git clone` 报 `Failed to connect ... after 21135 ms`） |

**后果**：

| 影响 | 说明 |
|---|---|
| ❌ `git clone` 不能用 | **代码必须用其他方式传过去**（我们提供了 zip 包） |
| ❌ 不能用 `tools/fetch_verilogeval_problem.py` 拉全量题集 | 该脚本从 GitHub 取数据 |
| ✅ 但可以装 Ollama | `ollama.com` 通 |

> ❓ 尚未测试该机器**是否有本地代理**。如果有（类似开发机的 `127.0.0.1:7897`），
> GitHub 可能可以走代理访问。测试命令：
> ```powershell
> Test-NetConnection 127.0.0.1 -Port 7897 -InformationLevel Quiet
> netsh winhttp show proxy
> ```

---

## 五、由此得出的限制

| 限制 | 原因 | 影响 |
|---|---|---|
| **不能 `git clone`** | GitHub 不可达 | 代码用 zip 包传输 |
| **不能拉全量 156 道题** | 题集从 GitHub 获取 | 只能用包里自带的 7 道题验证 |
| **不能验证容器** | 未装 Docker | 报告里"容器未验证"的条目继续保留 |
| **`serve/*.sh` 跑不了** | 是 bash 脚本，本机是 Windows | 需要在 WSL 或 Git Bash 下跑，或改为 PowerShell 版 |
| **ROCm 可能不可用** | 显卡是 GPU-PV（`VEN_1414`） | 需实测；可能要退到 Vulkan |
| **模型大小受限** | 内存只有 7.8 GB | 见下表 |

### 内存约束下的模型选型参考

| 模型 | Q4 文件大小 | 加载需要内存 | 7.8 GB 够吗 |
|---|---|---|---|
| `qwen2.5-coder:1.5b` | 1.0 GB | ~1.5 GB | ✅ 轻松 |
| `qwen2.5-coder:3b` | 1.9 GB | ~3 GB | ✅ 可以 |
| `qwen2.5-coder:7b` | 4.7 GB | ~6 GB | ⚠️ 勉强 |
| 32B 级 | ~20 GB | ~22 GB | ❌ 不行 |

**但要注意**：如果模型能**全部装进显存**（R9700 显存应该充足），就**不怎么占系统内存**。
这正是需要用 `ollama ps` 实测的东西。

---

## 六、待确认事项

| # | 问题 | 影响 |
|---|---|---|
| 1 | **这台机器允许安装软件吗？** | 决定模型服务能否在此验证 |
| 2 | **最终评测在哪台机器上？** | 决定为哪个环境适配 |
| 3 | **评测环境是容器吗？** | 决定 `Dockerfile` 的严格程度 |
| 4 | **是否有本地代理？** | 决定能否访问 GitHub |
| 5 | **R9700 的显存容量？** | 决定模型选型（Windows 的 `AdapterRAM` 字段不可靠） |

---

## 七、修订记录

| 时间 | 变更 |
|---|---|
| 初次勘察 | 记录 Windows 系统、R9700 显卡（VEN_1414）、7.8 GB 内存、E 盘 328 GB、Python 3.14.8 @E:\python、Vivado @E:\2025.2\Vivado、无 Docker、GitHub 不可达 |
