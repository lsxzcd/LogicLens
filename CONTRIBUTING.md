# LogicLens — 团队协作指南

面向 AMD FPGA 赛道 3.1（RTL/HLS 本地智能体设计赛道）的 RTL Track。本文件说明**如何在本仓库上协作**；项目现状与边界见 `README.md`，比赛报告见 `REPORT.md`。

---

## 1. 环境准备

必须：

- Python 3.11+（仅用标准库，见 `requirements.txt`）
- Vivado 2025.2（含 `xczu3eg-sbva484-1-e` 器件）
- 目标器件上的三级判定：`xvlog` / `xelab` / `xsim` / `synth_design`

Vivado 的解析顺序（无需修改代码即可适配各自机器）：

1. `--vivado <path>` 显式传入
2. 环境变量 `LOGICLENS_VIVADO`
3. `PATH` 中的 `vivado`
4. 内置候选路径（`D:\2025.2\Vivado\bin\vivado.bat` 等）

接模型推理服务（OpenAI 兼容）：

```powershell
$env:LOGICLENS_MODEL_URL  = "http://127.0.0.1:11434/v1/chat/completions"
$env:LOGICLENS_MODEL_NAME = "qwen2.5-coder:7b"
$env:LOGICLENS_API_KEY    = ""   # 可选
```

---

## 2. 提交前必须自检

```powershell
py -3 -m unittest discover -s tests      # 必须全绿，不需要 Vivado
```

改到判定流程时，额外跑真实工具验证（需要 Vivado，耗时数分钟）：

```powershell
py -3 experiments\p05_verify.py    # 三级判定：正例 / 组合逻辑 / 反例（综合门控）
py -3 experiments\tb_verify.py     # 生成的 testbench 必须能拒错误设计、纳正确设计
```

**硬性约定：**

- 单测必须全绿才能合并。CI（`.github/workflows/ci.yml`）会跑同一套。
- `experiments/runs/` 与 `experiments/results/` 是**产物**，已被 `.gitignore` 忽略，**不要 `git add -f`**。
- 不要把本机的绝对路径、模型权重、日志或 `dfx_runtime.txt` 提进仓库。
- `--mock` 的结果**只能**用于软件流程自检，**禁止**写入 `REPORT.md` 的实验结果。

---

## 3. 架构与扩展点

```
题目(question.txt)
  │
  ├─ agent/task_parser.py      规则优先解析 → TaskContract（端口/位宽/时钟/复位极性/边界）
  │                            解析不到的可选交给 parse_task_with_model()
  │
  ├─ agent/testbench.py        ★ resolve_testbench()：决定用哪个 testbench
  │                            优先级：--testbench > sidecar(<question>.tb.v) > 生成
  │
  ├─ agent/repair_policy.py    提示词；build_baseline_prompt() 只含题目原文
  │
  ├─ agent/controller.py       生成 → 验证 → 分类 → 局部修复 → 候选评分
  │   agent/baseline.py        同上但单次生成、不重试、不用技能包
  │
  ├─ agent/vivado_runner.py    调用 Vivado，带超时，落 flow_result.json
  │   vivado/run_flow.tcl      三级判定：xvlog → xelab → xsim → synth_design
  │
  └─ agent/evaluation.py       批量评测 → results.csv / summary.json / pass@k
      eval.py                  评测入口 CLI
```

### 三个协作边界（改动时请守住）

1. **测试台获取** 只走 `agent/testbench.py::resolve_testbench`。
   禁止再出现硬编码的 testbench 路径——这正是之前只支持一道题的根因。
   接 VerilogEval harness 只需把 `dataset_spec-to-rtl` 的题目导出为
   `<task>.txt`，并把其 testbench 放成 `<task>.tb.v` 同级文件。

2. **规格契约** 只经 `agent/task_parser.py::TaskContract`。
   新增字段请保持向后兼容（旧字段 `clock` / `reset` 仍被 CLI 与报告读取）。
   规则解析必须保持**确定性、可离线、可测试**；拿不准的字段留空，
   不要猜——`source` 字段用来区分「规则得到」与「默认值」。

3. **判定口径** 只在 `vivado/run_flow.tcl` 决定，字段含义固定：

   | 字段 | 含义 |
   |---|---|
   | `compile_pass` | `xvlog` 通过 |
   | `elaborate_pass` | `xelab` 通过 |
   | `simulation_pass` | `xsim` 出现 `TEST_PASS` 且无失败标记、未崩溃 |
   | `sim_crashed` | xsim 自身崩溃（**不是**设计的错） |
   | `synthesis_attempted` | 是否真的跑了综合（仿真未过则为 false） |
   | `synthesis_pass` | `synth_design` 成功 |
   | `timing_constraint_pass` | 5 ns 约束是否生效（无时钟端口时为「不适用」，记为 1） |

   赛题是**逐级递进**：前一级不过就不进入下一级。统计通过率时**必须**用
   `synthesis_attempted` 区分「没跑」和「跑了没通过」，否则三级通过率会偏高。

---

## 4. 分工建议

| 方向 | 负责 | 依赖的接口 |
|---|---|---|
| A. 数据集与测试台 | 导出 VerilogEval v2，准备 sidecar testbench | `resolve_testbench` |
| B. 智能体与技能包 | 规格提取补全、多候选生成、局部增量修复 | `TaskContract` |
| C. 模型与部署 | ROCm 推理服务、显存实测、`MODEL.md`、Dockerfile | `ModelClient` |

⏱️ **性能预期（实测）**：单题约 85 s，其中 `synth_design` 48 s + `report_timing_summary` 24 s，
**综合占约 85%，仿真只占 3.5%**。全量 156 题 × 5 采样 ≈ 18 小时机器时间。
批量评测务必先用 `eval.py --limit 10` 小规模验证，再决定并行度。

---

## 5. 分支与提交约定

- `main` 保持可运行、单测全绿；功能在 `feat/<topic>` 上做，修复在 `fix/<topic>`。
- 一个提交只做一件事，提交信息写**为什么**而不只是做了什么。
- 涉及判定口径或契约字段的改动，**必须**同时更新测试与本文档的对应表格。

常用命令：

```powershell
git checkout -b feat/verilogeval-harness
# ... 开发 ...
py -3 -m unittest discover -s tests
git add -A
git commit -m "feat: attach VerilogEval sidecar testbenches via resolve_testbench"
git push -u origin feat/verilogeval-harness
```

---

## 6. 已知边界（当前不要当作已完成）

- `agent/testbench.py` 只为**复位有界计数器**生成了行为级自检；其他题型落到
  冒烟测试（只驱动时钟、不做功能断言），**不能**当作功能正确性的证明。
- `parse_task_with_model` 是占位实现，模型兜底解析尚未接入。
- 产生 N 个候选再打分的选择机制尚未实现，目前是单候选串行重试。
- 未接 ROCm 模型服务，未做基于官方基础镜像的 Dockerfile。
- 组合逻辑题不施加 5 ns 时钟约束（无时钟端口），其 `timing_constraint_pass`
  记为「不适用」。
