# LogicLens 设计报告

> 本文件是比赛报告骨架。所有最终数据必须来自可复现的真实运行，不使用 mock 结果。

## 1. 项目概述

- 项目名称：LogicLens
- 参赛方向：RTL/HLS 本地智能体设计赛道 - RTL Track
- 核心目标：利用结构化题目规格、RTL 技能包和 Vivado 工具反馈，提高本地模型生成代码的编译、仿真和综合通过率。

## 2. 总体架构

```text
题目 -> 规格契约 -> RTL 生成 -> Vivado 验证
                                |
                         错误分类与局部修复
                                |
                         候选评分与结果记录
```

需要补充：

- 控制流和数据流图；
- 模型推理服务配置；
- 上下文管理方式；
- 重试停止条件；
- 断网运行方式。

## 3. 模型选择

记录至少两个候选模型：

| 模型 | 精度/量化 | 显存占用 | 选择或放弃原因 |
|---|---:|---:|---|
| 待填写 | 待填写 | 待实测 | 待填写 |

详细声明同步写入 `model/MODEL.md`。

## 4. 智能体设计

### 4.1 规格提取

说明端口、位宽、时钟、复位和边界条件如何形成结构化契约。

### 4.2 工具编排

说明 `xvlog`、`xelab`、`xsim` 和 `synth_design` 的调用顺序及超时策略。

### 4.3 错误分类与修复

列出语法、位宽、多驱动、锁存器、复位语义、仿真不一致和不可综合等错误类别。

### 4.4 候选选择

说明为什么优先选择“可综合 > 仿真通过 > 可编译”的候选，并记录重试成本。

## 5. 技能包

每条技能需要记录来源：

| 技能 | 原始失败 | 修复方法 | 验证题数 | 有效性结论 |
|---|---|---|---:|---|
| 待填写 | 待填写 | 待填写 | 0 | 待验证 |

## 6. 实验设计

### 6.1 数据集

- VerilogEval v2：待填写版本或提交哈希；
- 自建基础题集：待填写题目数量和类别。

### 6.2 环境

- GPU：待填写；
- ROCm：待填写；
- Vivado：2025.2，已实测；
- 目标器件：`xczu3eg-sbva484-1-e`；
- 时钟约束：5 ns；
- 模型和上下文配置：见 `model/MODEL.md`。

### 6.3 对照实验

同一模型、推理服务和上下文配置下比较：

1. `run_baseline.sh`：单次生成，不重试，不使用技能包。提示词由 `build_baseline_prompt` 生成，**只含题目原文**，不附加 RTL 规则或结构化契约（赛题明确要求绕过智能体与技能包，否则增益不可信）；
2. `run.sh`：完整智能体与技能包。

## 7. 实验结果

| 方案 | compile pass@1 | sim pass@1 | synth pass@1 | pass@5 | 平均耗时 |
|---|---:|---:|---:|---:|---:|
| Baseline | 待实测 | 待实测 | 待实测 | 待实测 | 待实测 |
| LogicLens | 待实测 | 待实测 | 待实测 | 待实测 | 待实测 |

禁止将 `--mock` 结果写入正式实验结果。

## 8. 失败分析

### 8.1 P0 复测结果

- 正例：`retest_final_correct` 在 `xczu3eg-sbva484-1-e` 上 `xvlog=1`、`xelab=1`、`xsim=1`、`synth_design=1`，5 ns XDC 与无未约束内部端点检查通过；
- 反例：`retest_final_wrong` 编译、展开和综合均可通过，但测试台报 `Fatal: hold check failed`，因此 `simulation_pass=0`，不会被智能体当作成功；
- Vivado 2025.2 在 `D:\FPGA` 直接运行 xsim 时曾出现 file-mapping 崩溃。现已将 xsim 临时工作目录放到系统 `%TEMP%`，证据仍保留在每次 `run_dir` 中。

### 8.2 P0.5 复测结果

本轮修复了 P0 遗留的三处判定口径问题，并补充了可执行验证脚本 `experiments/p05_verify.py`（真实 Vivado，非 mock）：

1. **综合门控**：综合现在只在仿真通过后执行。新增 `synthesis_attempted` 字段区分「未运行」与「运行且失败」，因此按级统计通过率时不会把跳过的综合算成通过。
2. **仿真失败标记收紧**：不再用裸子串 `error` 判定仿真失败（正确设计可能合法打印该词），改为匹配 `ERROR:` 与 `Fatal:` 这类明确标记；同时新增 `sim_crashed` 字段，把 xsim 自身崩溃与测试台报错分开记录。
3. **XDC 条件化**：`create_clock` 只对确实存在时钟端口的题目施加。`spec-to-rtl` 中含纯组合逻辑题（无 `clk` 端口），旧写法会让约束静默失效并把这类题判为失败；现在组合逻辑题的 `timing_constraint_pass` 记为适用而非失败。

验证覆盖三种用例，当前结果：

| 用例 | 断言 |
|---|---|
| `p05_clocked_ok`（正确计数器） | 编译/展开/仿真通过，`clock_port=clk`，综合被尝试 |
| `p05_comb_ok`（组合逻辑，无时钟） | 编译/展开/仿真通过，`clock_port=""`，综合被尝试 |
| `p05_clocked_wrong`（仿真必失败） | 编译/展开通过，`simulation_pass=0`，**`synthesis_attempted=0`** |

第三种用例是本轮门控修复的直接证据：仿真失败后综合不再执行，全部 8 项断言通过。

> 已知环境限制：在 DSH 沙箱受限令牌下手动调用 Vivado 时，`tclapp::load_apps` 会失败，导致 `read_xdc` 与 `synth_design` 报 `ERROR: [Common 17-39]`，与设计无关。此时 `synthesis_error` 字段会记录该原始错误，`p05_verify.py` 会把它标记为 `ENV` 而非 `FAIL`。正常 PowerShell 会话下该路径工作正常（见下节）。

### 8.2.1 全链路实测通过（目标器件、真实 Vivado 2025.2）

在不受沙箱限制的普通 PowerShell 会话中，以目标器件 `xczu3eg-sbva484-1-e` 完整跑通
`experiments/p05_verify.py`，结果为 **`3 cases, 0 failed assertion(s), 0 env-blocked`**：

| 用例 | compile | elaborate | simulation | synthesis_attempted | synthesis | timing_constraint | clock_port |
|---|---:|---:|---:|---:|---:|---:|---|
| `p05_clocked_ok` | 1 | 1 | 1 | 1 | **1** | **1** | `clk` |
| `p05_comb_ok`（无时钟端口） | 1 | 1 | 1 | 1 | **1** | **1** | `""` |
| `p05_clocked_wrong`（功能错误） | 1 | 1 | **0** | **0** | 0 | 0 | `clk` |

三条关键结论由此被实证：

1. **综合真的能跑通**，且 5 ns 时钟约束真的生效（`timing_constraint_pass=1`）；
2. **组合逻辑题不再被误判**：`clock_port` 为空时约束判定记为"适用"，而不是因
   `get_ports clk` 取空而失败——这正是 8.2 第 3 条修复的目标；
3. **综合门控真的生效**：功能错误的设计 `simulation_pass=0` 之后 `synthesis_attempted=0`，
   即"逐级递进"不仅写在代码里，而且在实际运行中成立。

综合产物已落盘可核验：`timing.rpt`（18,783 字节）、`utilization.rpt`（8,694 字节）。
单题墙钟约 56 秒。

> 环境说明：此验证只能在装有 Vivado 的机器上进行。CI 覆盖的是不需要 Vivado 的部分
> （单元测试、语法检查、架构守卫），因此"综合可综合"这一级的证据来自本机实测，
> 复现命令即上述脚本。

### 8.3 接口抽取与工程化改造

为使多人可并行开发，把原先硬编码的内部结构抽成三个稳定接口，并补齐了批量评测能力：

1. **测试台获取**统一走 `agent/testbench.py::resolve_testbench`，优先级为
   显式 `--testbench` > 同目录 sidecar（`<题目>.tb.v`）> 自动生成。
   此前 `data/examples/counter/tb.v` 被硬编码在 `controller.py` 与 `baseline.py`，
   导致换任何一道题都无法评测，这是原设计的单点瓶颈。
   现在接入 VerilogEval v2 只需把官方 testbench 放成 sidecar 文件。
2. **规格契约**由 `agent/task_parser.py` 规则优先解析：顶层模块名、端口方向与位宽、
   时钟名与边沿、复位名/极性/同步异步、以及 `enable` 限流等边界条件均可离线确定；
   无法确定的字段留空并标 `source="default"`，不猜测。
3. **批量评测**由 `agent/evaluation.py` 与 `eval.py` 提供：遍历题集，
   Agent 与裸基线各跑一遍，产出 `results.csv`、`summary.json`、pass@k 与增益表。

同时修复的缺陷：

- `synth_design` 在仿真失败时仍会执行，导致按级统计的三级通过率偏高；
  现改为门控并以 `synthesis_attempted` 区分「未运行」与「运行且失败」；
- 仿真失败判定原先包含裸子串 `error`，正确设计若合法打印该词会被误判，
  现改为匹配 `ERROR:` / `Fatal:` 明确标记，并新增 `sim_crashed` 区分仿真器崩溃；
- XDC 原先硬编码 `get_ports clk`，组合逻辑题会静默丢失约束并把好设计判为失败，
  现改为仅对确实有时钟端口的题目施加，组合逻辑题记为「不适用」；
- `subprocess` 调用 Vivado 没有超时，单题卡死会拖垮批量评测，现加入可配置超时；
- Vivado 路径除内置候选外，新增 `LOGICLENS_VIVADO` 环境变量覆盖；
- `--mock` 原先固定读取计数器的参考答案，现改为按题目同名 `<题目>.answer.v` 解析，
  缺失时明确报错。

验证规模：单元测试 40 个全绿（不需要 Vivado）；`experiments/p05_verify.py`、
`experiments/tb_verify.py`、`experiments/pipeline_verify.py` 三个脚本用真实 Vivado
验证判定、testbench 与端到端链路。

## 9. 复现说明

需要补充官方基础镜像、容器构建命令、模型权重校验和、单题运行命令及完整评测命令。

## 10. 当前已知边界

- 生成的 testbench 只为**复位有界计数器**做行为级自检，其他题型落到冒烟测试
  （仅驱动时钟），因此除计数器外的题目尚无功能正确性证明；接入 VerilogEval 官方
  testbench（sidecar）后可覆盖全集；
- `parse_task_with_model` 仍为占位实现，模型兜底解析尚未接入；
- 尚未接入 ROCm 本地模型服务，`model/MODEL.md` 待填写；
- 尚未制作基于官方基础镜像的 Dockerfile，断网运行未验证；
- 尚无真实实验数据，第 7 节待 `eval.py` 产出后回填；
- 产生 N 个候选再打分的选择机制未实现，目前是单候选串行重试。
