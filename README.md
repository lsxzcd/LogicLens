# LogicLens RTL Agent

LogicLens 是一个面向 AMD FPGA 赛道 3.1（RTL/HLS 本地智能体设计赛道）**RTL Track** 的工程原型。
它把自然语言硬件题目转换为 Verilog，调用 AMD Vivado 2025.2 完成**编译 → 仿真 → 综合**三级递进判定，
并按错误类型做有限次数的修复重试。

正式报告见 `REPORT.md`，团队协作约定见 `CONTRIBUTING.md`。

## 当前状态（先读这一节）

**已跑通并验证（在目标器件 `xczu3eg-sbva484-1-e` 上用真实 Vivado 2025.2 实测）：**

- 三级判定流程真机跑通：`xvlog` → `xelab` → `xsim` → `synth_design`，
  综合阶段带 5 ns 时钟约束，`experiments/p05_verify.py` 输出
  **`3 cases, 0 failed assertion(s), 0 env-blocked`**；
- 仿真失败会被正确识别（`TEST_PASS` + 无失败标记 + 未崩溃三重校验），
  **仿真不过则不再进入综合**（实测 `synthesis_attempted=0`），符合赛题"逐级递进"口径；
- 组合逻辑题（无 `clk` 端口）不再丢失时序约束判定，记录为"适用"而非失败；
- 测试台可插拔：`agent/testbench.py::resolve_testbench` 统一决定用哪个 testbench，
  支持显式指定 / sidecar 文件 / 自动生成，且生成的 counter testbench 已实测能
  **拒绝错误设计、接纳正确设计**；
- 批量评测入口 `eval.py` 能产出 `results.csv`、`summary.json` 与 pass@k 增益表；
- 单元测试 40 个全绿（不需要 Vivado），CI 在 GitHub 上自动执行。

**尚未完成（不要当作已完成）：**

- 只为**复位有界计数器**生成了行为级自检 testbench，其他题型落到冒烟测试，**不能证明功能正确性**；
- 未接入任何模型服务；`model/MODEL.md` 仍是待填写；
- 未接 ROCm，未做基于官方基础镜像的断网 Dockerfile；
- 尚无真实实验数据（`experiments/results/` 为空），`REPORT.md` 第 7 节待回填；
- 产生 N 个候选再打分的选择机制未实现，目前是单候选串行重试。

## 快速开始

```powershell
# 1) 软件流程自检（不需要 Vivado 和模型服务）
py -3 run.py --question data/examples/counter/question.txt --mock

# 2) 单元测试
py -3 -m unittest discover -s tests -v
```

`--mock` 模式需要题目同级有参考答案 `<题目名>.answer.v`，否则会明确报错
（不会像以前那样悄悄拿计数器的答案去跑别的题）。

### 接入本地模型

```powershell
$env:LOGICLENS_MODEL_URL  = "http://127.0.0.1:11434/v1/chat/completions"
$env:LOGICLENS_MODEL_NAME = "qwen2.5-coder:7b"
$env:LOGICLENS_API_KEY    = ""     # 可选
py -3 run.py --question data/examples/counter/question.txt
```

### 接入 Vivado

`vivado` 的解析顺序：`--vivado` 参数 → 环境变量 `LOGICLENS_VIVADO` → `PATH`
→ 内置候选路径（`D:\2025.2\Vivado\bin\vivado.bat` 等）。

```powershell
$env:LOGICLENS_VIVADO = "D:\2025.2\Vivado\bin\vivado.bat"
py -3 run.py --question data/examples/counter/question.txt
```

赛题目标器件已内置：`xczu3eg-sbva484-1-e`。本机没装该器件时可临时用
`LOGICLENS_TARGET_PART` 换器件做流程验证，**但这不能替代目标器件上的最终结果**。

### 指定 testbench

```powershell
# 自动：显式 > sidecar(<题目名>.tb.v) > 生成
py -3 run.py --question experiments/dataset_smoke/alu_comb.txt

# 强制使用指定文件 / 强制生成
py -3 run.py --question Q.txt --testbench my_tb.v
py -3 run.py --question Q.txt --testbench-mode generated
```

### 批量评测

```powershell
# 先小规模验证链路（务必先跑 --limit）
py -3 eval.py --dataset experiments/dataset_smoke --mode both --mock --samples 3

# 正式评测：Agent 与裸模型基线各跑一遍，输出 pass@1 / pass@5 与增益表
py -3 eval.py --dataset <VerilogEval导出目录> --mode both --samples 5 --out experiments/results/run1
```

数据集约定：目录下每个 `<task>.txt`/`.md` 是一道题；同级的 `<task>.tb.v`
（testbench）与 `<task>.answer.v`（参考答案）会被自动识别。接 VerilogEval v2 的
`dataset_spec-to-rtl` 只需按其格式导出，并把官方 testbench 放成 sidecar 文件。

## 目录说明

```text
agent/       题目解析、模型调用、testbench 解析、错误分类、修复策略、Vivado 调度、批量评测
data/        示例题目、参考答案和测试台
experiments/ 数据集与运行产物（runs/ 与 results/ 已在 .gitignore 中）
model/       模型来源与版本说明
skill/       RTL 提示词和错误修复知识
ui/          离线 HTML 运行报告生成器
vivado/      Vivado Tcl 三级判定脚本
tests/       单元测试（不需要 Vivado）
eval.py      批量评测入口
```

## 判定字段口径

| 字段 | 含义 |
|---|---|
| `compile_pass` | `xvlog` 通过 |
| `elaborate_pass` | `xelab` 通过 |
| `simulation_pass` | `xsim` 打印 `TEST_PASS`、无 `ERROR:`/`Fatal:`、且未崩溃 |
| `sim_crashed` | xsim 自身崩溃（不算设计的错） |
| `synthesis_attempted` | 是否真的跑了综合（仿真未过则为 false） |
| `synthesis_pass` | `synth_design` 成功 |
| `synthesis_error` | 综合失败原因（用于区分环境问题与设计问题） |
| `timing_constraint_pass` | 5 ns 约束是否生效；无时钟端口的组合逻辑题记为「适用」 |

**统计三级通过率时必须用 `synthesis_attempted` 区分「没跑」与「跑了没通过」**，
否则通过率会偏高。

## 验证脚本

```powershell
py -3 experiments\p05_verify.py        # 三级判定：正例 / 组合逻辑 / 反例（综合门控）
py -3 experiments\tb_verify.py         # 生成的 testbench 必须能拒错纳对
py -3 experiments\pipeline_verify.py   # 端到端：正确设计通过、语法错误设计被拦下
```

## 下一步

1. 导出 VerilogEval v2 `dataset_spec-to-rtl` 并准备 sidecar testbench；
2. 接入 ROCm 本地模型服务，实测显存（须 ≤ 单卡 32 GB），填满 `MODEL.md`；
3. 用 `eval.py` 产出真实 pass@1 / pass@5 与增益数据，回填 `REPORT.md`；
4. 扩充技能包（每条规则记录来源失败、修复方法、验证题数、有效性）；
5. 制作基于官方基础镜像的断网 Dockerfile。
