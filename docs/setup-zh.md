# 环境搭建与 Vivado 配置

面向团队每位成员。**每台机器只需配一次。**

---

## 1. 必需软件

| 软件 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 只用标准库，无需 pip 安装任何东西 |
| AMD Vivado | 2025.2 | 三级判定用；**必须含 `xczu3eg-sbva484-1-e` 器件** |
| Git | 任意 | 若没装，可用 GitHub Desktop 自带的（见第 4 节） |

`py -3 -m unittest discover -s tests` **不需要 Vivado**，只跑单测的话装了 Python 就能开始。

---

## 2. Vivado / Vitis 路径：**不需要手工告诉我，会自动找到**

`agent/vivado_runner.py` 按以下顺序解析，命中即用：

1. `--vivado <路径>` 命令行显式指定
2. 环境变量 `LOGICLENS_VIVADO`
3. `PATH` 中的 `vivado` / `vivado.bat`
4. 内置候选路径：
   - `D:\2025.2\Vivado\bin\vivado.bat` ← **AMD 统一安装器的默认布局**
   - `D:\Xilinx\Vivado\2025.2\bin\vivado.bat`
   - `C:\Xilinx\Vivado\2025.2\bin\vivado.bat`
   - `C:\Program Files\Xilinx\Vivado\2025.2\bin\vivado.bat`
   - `/tools/Xilinx/Vivado/2025.2/bin/vivado`、`/opt/Xilinx/Vivado/2025.2/bin/vivado`

Vitis（HLS Track 用）同理，环境变量是 `LOGICLENS_VITIS`，内置候选为
`D:\2025.2\Vitis\bin\vitis.bat` 等。

### 验证是否找到

```powershell
py -3 -c "from agent.vivado_runner import locate_vivado, locate_vitis; print('vivado:', locate_vivado(None)); print('vitis :', locate_vitis(None))"
```

本机实测输出：

```
vivado: D:\2025.2\Vivado\bin\vivado.bat
```

`locate_vivado` 返回 `None` 说明顺序里的位置都没命中，这时才需要显式设置：

```powershell
# 只对当前窗口生效
$env:LOGICLENS_VIVADO = "D:\2025.2\Vivado\bin\vivado.bat"

# 或永久写入用户环境变量
[Environment]::SetEnvironmentVariable("LOGICLENS_VIVADO", "D:\2025.2\Vivado\bin\vivado.bat", "User")
```

### 为什么 xvlog / xelab / xsim 不用配

三级判定不直接调用它们，而是由 `vivado -mode batch -source vivado/run_flow.tcl` 触发。
Vivado 启动时会把 **自己的 `bin` 目录放进子进程的 PATH**，所以 `run_flow.tcl` 里
直接写 `exec xvlog ...` 就能找到——即使 `xvlog` 不在你的系统 PATH 里。

> 注意：这也意味着**不能在普通 shell 里直接跑 `xvlog`**。要在命令行单独用它，
> 得自己把 `D:\2025.2\Vivado\bin` 加进 PATH。`experiments/tb_verify.py`
> 就是通过推导 `vivado.bat` 的所在目录来定位这三个可执行文件的。

### 器件检查

```powershell
D:\2025.2\Vivado\bin\vivado.bat -mode batch -nolog -nojournal -source D:\FPGA\vivado\run_flow.tcl
```

更简单的替代：跑一次真实验证，如果综合报 `Invalid option value specified for '-part'`
说明该器件未安装。

---

## 3. 验证本地环境

```powershell
cd D:\FPGA

# 1) 不需要 Vivado 的部分（应全绿，51 个测试）
py -3 -m unittest discover -s tests

# 2) 三级判定全链路（需要 Vivado，约 3 分钟）
py -3 experiments\p05_verify.py
#    期望：3 cases, 0 failed assertion(s), 0 env-blocked

# 3) VerilogEval 官方 testbench 在 xsim 下可用（需要 Vivado，约 1 分钟）
py -3 experiments\verilogeval_verify.py
#    期望：0 failed check(s)
```

**第 2、3 步是本项目的关键验证**，因为它们覆盖 CI 无法覆盖的部分（CI 不跑 EDA 工具）。

---

## 4. Git：本机没装 git 时

若 `git` 不在 PATH，用 GitHub Desktop 自带的：

```cmd
set PATH=%LOCALAPPDATA%\GitHubDesktop\app-3.5.2\resources\app\git\cmd;%PATH%
```

或使用仓库里的加载脚本（PowerShell）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\git-env.ps1
```

---

## 5. 代理（仅网络受限时需要）

若 `git clone` / `git push` 报 `Connection was reset`，而浏览器能打开 GitHub，
说明需要给 git 单独配代理（git **不读取** Windows 系统代理）：

```cmd
git config --global http.proxy  http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
```

端口按自己的代理客户端填。详见 [push-to-github-zh.md](push-to-github-zh.md)。

---

## 6. 模型推理服务（接入模型时才需要）

```powershell
$env:LOGICLENS_MODEL_URL  = "http://127.0.0.1:11434/v1/chat/completions"
$env:LOGICLENS_MODEL_NAME = "qwen2.5-coder:7b"
$env:LOGICLENS_API_KEY    = ""   # 可选
```

未配置时只能跑 `--mock`，它会用 `<题目>.answer.v` 或 `<stem>_ref.sv` 作为
参考答案来检验软件流程，**不是真实模型结果**。
