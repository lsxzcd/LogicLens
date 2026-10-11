# 给 C 的回复：Vivado 综合崩溃的分析与下一步

> 回复对象：队友 C
> 日期：2026-10-12
> 针对你的交接包：`LogicLens-实验室验证交接包-20261011.zip`
> 依据的代码版本：`87cc7d0a72c2617557b9a0abf4d6a50f9c832d0d`（与你的记录一致）

---

## 一、先说结论

**你的工作质量很高，而且你发现的两件事修正了我之前的错误判断。** 具体见 §2。

**核心阻塞（Vivado 综合崩溃）我做了根因分析，有一个强证据表明这是那台机器的环境问题，不是我们的代码问题。** 见 §3。

**下一步有两个 2 分钟的测试，很可能直接解决问题。** 见 §4。

**另外有一个被忽略的机会：仿真没有崩，所以我们可以现在就拿到真实的功能正确性数据。** 见 §5。

---

## 二、你的工作里，我要特别指出的几点

### 2.1 你修正了我的两个错误

| 我之前记的 | 你的实测 | 影响 |
|---|---|---|
| GitHub 不可达，代码必须用 zip 传 | **`codeload.github.com` 可以访问**，你就是这样下载的 | 我的"必须用 zip"结论过于绝对；后续可以让队友直接 codeload 下载 |
| 实验室机器内存 7.8 GB | **当前可用 13.7 GB，最大 16 GB** | 我基于 7.8 GB 做的"模型只能选 1.5B~3B"推论不成立 |

**这两个修正很重要，我已经记下要改文档。**

### 2.2 你做得对的地方（我认为值得保持的习惯）

1. **记录了代码提交哈希** —— 让所有结论可追溯到具体版本
2. **严格区分"实测"与"未证明"** —— 例如你明确写了
   "size 与 size_vram 相等…**支持**该短请求下模型完整 GPU 卸载的**初步判断**。不是设备总显存峰值或长期稳定性证明"
3. **主动标注证据来源的可靠性** —— 你标明哪些是"用户回传终端输出整理的报告，不是实验室原始文件"，
   这比把转录当成原始证据诚实得多
4. **没有越界** —— 未改 `vivado/run_flow.tcl`、未重装软件、未改系统安全设置
5. **区分数值口径** —— 你特别指出 `ps.json` 是 2048 上下文、`service-measurements-7b.json` 是 8192 上下文，
   **不能混用显存数值**。这个自觉性很关键

### 2.3 唯一的建议

`01-实验室勘察记录.md` 里的信息很丰富，但**结论分散在各段**。
建议以后在文件开头加一个 **3~5 行的"要点"区块**，让读的人先抓住最重要的几条。
（你 `00-给队长的说明.md` 就是这么做的，非常好——其他文件可以照这个格式。）

---

## 三、Vivado 综合崩溃：我的根因分析

### 3.1 关键证据：**同一台开发机用完全相同的版本和器件，综合成功了**

这是最重要的对照，之前没人做：

| 对比项 | 实验室机器 | 开发机（队长） |
|---|---|---|
| Vivado 版本 | 2025.2，**SW Build 6299465** | 2025.2，**SW Build 6299465** |
| 目标器件 | `xczu3eg-sbva484-1-e` | **完全相同** |
| 被测电路 | `counter`、`alu_comb` | **相同的电路** |
| 运行的 TCL | `vivado/run_flow.tcl` | **同一份文件** |
| **结果** | 🔴 崩溃 `0xC0000374` | ✅ **成功，`synthesis_pass=1`，110 秒** |

**这一个对照同时排除了四种可能**：

| 被排除的假设 | 依据 |
|---|---|
| ❌ 我们的 Tcl 流程有 bug | 同一份脚本在一台机器上成功 |
| ❌ 目标器件不支持 | 同一器件综合成功 |
| ❌ 缺 Synthesis 许可证 | 你的日志明确 `Got license for feature 'Synthesis' and/or device 'xczu3eg'` |
| ❌ 内存不足 | **综合峰值内存仅 1764 MB**（日志有记录），而机器有 13.7 GB 可用 |

**所以第一步的定位是：这是实验室那台机器的环境问题。**

### 3.2 崩溃位置：固定在多进程 helper 启动之后

你贴的日志尾部（`evidence/01`）显示，两次崩溃的最后几行完全同构：

```
INFO: [Synth 8-7079] Multithreading enabled for synth_design using a maximum of 2 processes.
INFO: [Synth 8-7078] Launching helper process for spawning children vivado processes
INFO: [Synth 8-7075] Helper process launched with PID 4396
INFO: [Synth 8-6155] done synthesizing module 'counter'          ← 最后一行
（进程消失）
```

**两次都在"综合完第一个模块、开始多进程并行"之后立即退出。**

`0xC0000374` 是 `STATUS_HEAP_CORRUPTION`（堆损坏），它在 Windows 上通常指向
**内存管理被干扰**，而不是业务逻辑错误。

### 3.3 两个可疑方向（按我的怀疑程度排序）

#### 方向 ①：AMD 图形驱动干扰 ⭐ 我的主要怀疑

**你自己已经发现了这个线索**：Ollama 服务日志写着

```
AMD driver is too old
（驱动版本 25.20.42.14 (LLPC)，来自 vulkaninfo）
```

**为什么这可能与 Vivado 崩溃有关**：

图形驱动的 DLL（`atio6axx.dll`、`amdxx*.dll` 等）会被加载进**每一个**用户态进程（Windows 的
图形栈设计如此），Vivado 也不例外。在一台**GPU 半虚拟化**（`VEN_1414`）且**驱动过旧**的虚拟机上，
驱动与进程堆管理的冲突是 `0xC0000374` 的经典成因之一。

#### 方向 ②：综合 helper 多进程

崩溃点固定在 `Launching helper process` 之后，而 `synth_design` 默认开 **2 个进程**。

**注意**：你试过的 `set_param general.maxThreads 1` **可能没有真正限制 helper 进程数**——
那个参数控制的是综合算法内部的线程，而 helper 是用于**派生并行子进程**的独立机制。
所以这个方向**还没被真正测过**。

---

## 四、请做两个测试（每个约 2 分钟）

> 顺序很重要：**先做测试 1**。如果它解决了问题，方向 ② 就是根因，改动最小。

### 测试 1：尝试强制单进程综合 ⭐ 优先

> ⚠️ **先说清楚不确定性**：我**无法确认** `synth_design` 的确切参数名。
> AMD 的官方 TCL 命令文档是 JS 渲染页面，我抓不到内容；我也没有 Vivado 可以本地验证。
>
> **所以这一步分两小步：先花 30 秒确认参数存在，再执行。** 不要跳过第一小步。

#### 1a. 先确认参数名（30 秒）

在实验室机器的 PowerShell 里：

```powershell
cd E:\LogicLens-87cc7d0a72c2617557b9a0abf4d6a50f9c832d0d\LogicLens-87cc7d0a72c2617557b9a0abf4d6a50f9c832d0d
& 'E:\2025.2\Vivado\bin\vivado.bat' -mode tcl -nojournal -nolog
```

出现 `Vivado%` 后，输入：

```tcl
help synth_design
```

**在输出里找与"并行/进程/job"相关的选项**，例如 `-jobs`、`-maxThreads`、`-directive` 之类。

**把那一行或那几行贴回来。** 如果 `help synth_design` 输出太长，可以试：

```tcl
help synth_design | grep -i -E "job|thread|process"
```

（如果 `grep` 在 Vivado 的 Tcl 里不可用，就用 `help synth_design` 全量输出，我们人工找。）

#### 1b. 用确认过的参数跑最小案例

假设 `help` 显示确实有 `-jobs`（**如果没有，请用 `help` 里实际存在的那个参数名**）：

```tcl
read_verilog -sv ./experiments/p05_inputs/alu_comb.v
synth_design -top alu_comb -part xczu3eg-sbva484-1-e -jobs 1
```

**为什么值得试这个**：崩溃点固定出现在 `Launching helper process` 之后，
而 `synth_design` 默认会派生子进程做并行综合。
你试过的 `set_param general.maxThreads 1` **可能只限制了综合算法内部的线程数**，
**没有限制 helper 的子进程数**——这是两套不同机制。

| 结果 | 含义 | 下一步 |
|---|---|---|
| ✅ 综合完成（看到 *Synthesis finished* 之类输出） | **找到根因**：helper 多进程问题 | 队长在 `run_flow.tcl` 里以参数形式加入，代价只是综合慢一点 |
| 🔴 仍崩溃（同样的退出码） | 排除多进程，转向方向 ①（驱动） | 做测试 2 |
| ⚠️ 参数不存在 | 说明我记错了 | 用 `help synth_design` 里的实际参数名替代 |

**请把完整输出贴回来**（包括 `Vivado%` 提示符和最终退出）。

### 测试 2：查 Windows 事件日志里的**故障模块名**

**这一步能把"怀疑"变成"证据"。** 用**管理员** PowerShell：

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddDays(-3)} -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'vivado' } |
  Select-Object -First 3 TimeCreated, Message | Format-List
```

**要看的字段是 `Faulting module name`**：

| 故障模块 | 指向 | 建议动作 |
|---|---|---|
| **`atio6axx.dll`** / `amdvlk*.dll` / `amdxx*.dll` | ⭐ **AMD 驱动冲突** | 请实验室升级显卡驱动，或在另一台机器上验证 |
| `ntdll.dll`，或字段为空 | 内存管理问题 | 仍可能指向驱动 |
| `vivado.exe` 自身的 dll | Vivado 安装损坏 | 请实验室修复安装 |

**注意你之前查过一次但被 `SilentlyContinue` 隐藏了输出**——你已经在报告里诚实标注了这一点。
这次**不要加 `-ErrorAction SilentlyContinue` 到 `Where-Object` 后面**，或者改成先取到事件再筛选。

如果这条命令没输出，试试不带 vivado 筛选、只看最近的应用程序错误：

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000} -MaxEvents 10 -ErrorAction SilentlyContinue |
  Select-Object TimeCreated, @{n='Msg';e={$_.Message.Substring(0,[Math]::Min(400,$_.Message.Length))}} | Format-List
```

---

## 五、⭐ 一个被忽略的机会：综合崩了，但仿真没崩

这是我觉得最值得立刻做的事。

### 5.1 为什么这件事重要

赛题的三级判定是**逐级递进**的：

```
可编译 → 仿真通过 → 可综合
```

**"仿真通过"是含金量最高的那一级**——它检验**功能正确性**（与官方参考实现逐拍对比）。
而**综合崩溃只影响第三级，不影响前两级的解读**。

### 5.2 而你已经在实验室机器上验证了：7B 模型能跑在 GPU 上

| 你实测的 | 值 |
|---|---|
| 模型 | `qwen2.5-coder:7b`，Q4_K_M |
| **`size_vram`** | **5,119,263,374 字节（约 4.77 GiB）** |
| 上下文 | 8192（`service-measurements-7b.json`） |
| `ollama ps` | **100% GPU** |
| ModelClient 接入 | ✅ `check_model.py` → ok=True |

**这意味着我们现在就能拿到真实的模型产出质量数据，而不用等综合问题解决。**

### 5.3 请执行：用 7B 跑 5 道真实题目

> ⚠️ 前提：Ollama 服务在运行，且模型已拉取。
> 你说过服务只监听 `127.0.0.1:11434`——**这没问题，我们也是本机调用**。

```powershell
cd E:\LogicLens-87cc7d0a72c2617557b9a0abf4d6a50f9c832d0d\LogicLens-87cc7d0a72c2617557b9a0abf4d6a50f9c832d0d

$env:LOGICLENS_MODEL_URL  = "http://127.0.0.1:11434/v1"
$env:LOGICLENS_MODEL_NAME = "qwen2.5-coder:7b"
$env:LOGICLENS_SEED       = "1"
$env:LOGICLENS_VIVADO     = "E:\2025.2\Vivado\bin\vivado.bat"

python eval.py --dataset experiments\data\verilogeval --mode agent --limit 5 --samples 1 `
    --out experiments\results\lab_7b_probe
```

**耗时估计**：约 15~25 分钟（5 道题，含模型生成和仿真）。

### 5.4 产出什么、怎么解读

结果在 `experiments/results/lab_7b_probe/agent/` 下的 `summary.json` 和 `results.csv`。

**重点看这几个字段**：

| 字段 | 含义 | 预期 |
|---|---|---|
| `compile_pass_rate` | 编译通过率 | 应该较高 |
| **`simulation_pass_rate`** | **仿真通过率 ⭐ 这是我们要的真实数据** | 未知，这才是重点 |
| `synthesis_attempted` | 是否尝试综合 | 仿真通过的那几道会是 1 |
| `synthesis_pass_rate` | 综合通过率 | **会因为崩溃为 0，可以忽略** |
| `error_types` | 失败类型分布 | 用于技能包提炼 |

**⚠️ 一个重要的解读提醒**：

因为综合会崩溃，**`success_rate` 一定是 0**（`success` 要求三级全过）。
**不要把这个 0 当作"7B 模型不行"** —— 请**只看 `simulation_pass_rate`**，
它才是这台机器上能拿到的**真实功能正确性数据**。

**请在报告里明确写这一点**，避免后来的人误读。

### 5.5 顺便请采集一个数据

跑之前，请记录 `ollama ps` 的输出（含 `CONTEXT` 和 `SIZE`），
因为**上下文长度会影响显存占用**，而 `MODEL.md` 需要准确的对应关系。

---

## 六、如果两个测试都没解决问题

那就**接受这是环境限制，不要继续在上面花时间**。理由是：

1. **我们已经用开发机证明了流程正确**（同版本同器件综合成功）
2. **赛题最终评测环境大概率不是这台机器**（赛题要求的是"基于官方基础镜像的容器"）
3. **这台机器仍然很有价值**——它能产出**编译 + 仿真**两级的真实数据，这已经覆盖了主要判定

**可以让老师协调的事**（按性价比）：

| 请求 | 理由 |
|---|---|
| **在另一台机器跑同一个最小案例** | 最终裁决，能确认是机器问题 |
| **升级 AMD 显卡驱动** | 如果测试 2 指向驱动 |
| **给虚拟机更多内存/调整配置** | 备用方向 |

**同时请老师明确一件事**（这是我最想知道的）：
> **最终评测是在这台机器上，还是在赛事方提供的容器环境里？**

如果答案是"容器环境"，那么这台机器的 Vivado 崩溃**只是开发期障碍，不影响提交**。

---

## 七、请不要做的事（沿用你之前的自觉）

| 不要做 | 原因 |
|---|---|
| ❌ 不要重装 Vivado | 几十 GB，且未确认安装损坏 |
| ❌ 不要升级显卡驱动 | 需要管理员权限，且可能影响老师的环境 |
| ❌ 不要改 `vivado/run_flow.tcl` | 由队长维护；如果 `-jobs 1` 有效，队长会以参数形式加入 |
| ❌ 不要改系统安全设置 | 同上 |
| ❌ **不要把综合崩溃当成我们代码的缺陷** | §3.1 的对照已排除这个可能 |

---

## 八、回传格式建议

请按这个结构回复（方便我直接并入项目文档）：

```
## 测试 1（-jobs 1）
结果：成功 / 仍崩溃
完整输出：（粘贴）

## 测试 2（事件日志）
Faulting module name：
其它相关字段：
（如果无输出，也请说明）

## 7B 模型 5 题评测
compile_pass_rate：
simulation_pass_rate：
synthesis_attempted：
error_types：
ollama ps 的 CONTEXT / SIZE：
耗时：
原始文件位置：

## 其它发现
```

**如果你的结论是"某条命令没输出/不确定"，请照实写**——你的报告里已经这样做得很好了，
这比给一个不确定的肯定结论有价值得多。

---

## 九、我这边会同步做的

1. 把你在 `01-实验室勘察记录.md` 里的**准确数据**并入 `docs/lab-machine-facts-zh.md`
   （修正我之前写的 7.8 GB、GitHub 不可达等错误）
2. 把 **7B 的 `size_vram` = 5.12 GB @ 8192 上下文**填进 `model/MODEL.md`（这是赛题要的显存证据）
3. 把 **Vivado 崩溃**记进 `docs/status-log-zh.md`，附 §3.1 的对照分析
4. 在 `CONTRIBUTING.md` 或验证文档里**注明实验室环境是 Windows**，
   避免再有人按 Linux 准备（这是我之前犯的错，你提出的问题很对）

---

**最后再说一次：你的交接包质量很高。** 尤其是"明确区分实测与未证明"、
"标注证据来源可靠性"、"未越界修改公共文件"这三点，正是团队协作最需要的东西。

下一步的阻塞很可能就是 `-jobs 1` 那一条命令。**先做它。**
