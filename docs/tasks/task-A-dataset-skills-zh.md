# 队友 A · 第一周任务书：数据集与技能包

> **这份文档可以直接转发给队友，不需要额外口头解释。**
> 有问题先看文末「卡住了怎么办」。

---

## 0. 背景（30 秒版）

我们在做一个**本地 RTL 设计智能体**（LogicLens），参加全国大学生嵌入式芯片与系统设计竞赛 AMD FPGA 赛道 RTL Track。

它做的事：**读自然语言题目 → 生成 Verilog → 用真实 Vivado 三级判定（编译/仿真/综合）→ 失败就局部修复**。

**你的方向**：扩充评测数据集，并把"模型犯过的错"提炼成可复用的技能包。

### 关键认知（很重要）

赛题明确要求：

> 将**失败诊断经验**提炼为**他人可复用的技能包**

所以技能包**不是**写通用 RTL 规范，而是**从真实失败中提炼**。这也是本任务书的核心。

另一件必须先知道的事：**目前只有 5 道题的真实失败数据**，所以现有技能卡只有 6 张。
你的任务是把数据量和技能卡数量都做上去。

---

## 1. 环境准备（10 分钟）

**只需要 Python 3.11+**，项目**只用标准库**，不需要 pip install。

```bash
git clone https://github.com/lsxzcd/LogicLens.git
cd LogicLens
python3 -m unittest discover -s tests
```

**预期输出**：

```
Ran 124 tests in 9.1s

OK
```

⚠️ **如果不是 `OK`，先停下来在群里说**，不要继续。

再跑两条：

```bash
python3 tools/check_architecture.py     # 预期：architecture guard: no hardcoded testbench path in agent/
python3 tools/check_parsing.py          # 预期：0 unexplained
```

`check_parsing.py` 的完整预期输出：

```
===== 156 task(s), 153 fully correct, 2 known upstream issue(s), 1 unnamed, 0 unexplained =====
```

---

## 2. 任务 A1：导出并分析全量数据集（第一天）

### 2.1 导出

仓库**只跟踪了 7 道题**（全量 470 KB，设计上不入库）。导出全量：

```bash
python3 tools/fetch_verilogeval_problem.py --all experiments/data/verilogeval
```

**预期**：`experiments/data/verilogeval/examples/` 下出现 **156 × 3 = 468 个文件**
（`_prompt.txt` / `_test.sv` / `_ref.sv` 三件套）。

验证：

```bash
ls experiments/data/verilogeval/examples/*_prompt.txt | wc -l    # 预期 156
```

### 2.2 跑一遍解析核对

```bash
python3 tools/check_parsing.py
```

**预期仍是 `0 unexplained`**。如果有 unexplained，**立刻报告**——说明解析器有缺陷。

### 2.3 按题型分类（这是你要产出的第一份数据）

写一个分析脚本，对 156 道题分类统计。建议维度：

| 维度 | 怎么判断 |
|---|---|
| 组合逻辑 vs 时序 | 契约里有没有时钟端口（`contract.ports` 里有 `clk` 之类） |
| 端口数量 | `len(contract.ports)` |
| 位宽分布 | 位宽 > 1 的端口数量 |
| 是否含复位 | 端口里有 `rst`/`reset` 之类 |
| FSM | 题面含 `state`/`FSM`/`transition` 等关键词 |

参考代码（`experiments/analyze_dataset.py`）：

```python
import sys, json, re
from pathlib import Path
sys.path.insert(0, ".")
from agent.task_parser import parse_task

examples = Path("experiments/data/verilogeval/examples")
rows = []
for prompt in sorted(examples.glob("*_prompt.txt")):
    contract = parse_task(prompt.read_text(encoding="utf-8"))
    has_clock = any("clk" in p.name.lower() or "clock" in p.name.lower() for p in contract.ports)
    rows.append({
        "stem": prompt.name.replace("_prompt.txt", ""),
        "sequential": has_clock,
        "ports": len(contract.ports),
        "wide_ports": sum(1 for p in contract.ports if p.width > 1),
        "has_reset": any("rst" in p.name.lower() or "reset" in p.name.lower() for p in contract.ports),
        "fsm": bool(re.search(r"\bstate\b|\bFSM\b|transition", contract.raw_text, re.I)),
    })

print(f"total: {len(rows)}")
print(f"combinational: {sum(1 for r in rows if not r['sequential'])}")
print(f"sequential: {sum(1 for r in rows if r['sequential'])}")
print(f"with reset: {sum(1 for r in rows if r['has_reset'])}")
print(f"FSM-like: {sum(1 for r in rows if r['fsm'])}")
Path("experiments/results").mkdir(parents=True, exist_ok=True)
Path("experiments/results/dataset_analysis.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
```

**产出**：`experiments/results/dataset_analysis.json` + 一份分类结论（写在 PR 描述里）

### 2.4 挑 20~30 道代表性题目

从分类结果里选一批，覆盖：
- 纯组合逻辑（无时钟）≥ 5 道
- 简单时序 ≥ 5 道
- 含复位 ≥ 5 道
- FSM ≥ 3 道
- 宽位宽/向量操作 ≥ 3 道

**产出**：一份题目清单，写在 PR 描述里。

---

## 3. 任务 A2：扩充技能包（核心交付）

### 3.1 先读懂现有格式

```bash
python3 -m json.tool skill/skill_cards.json | head -60
```

每张卡的字段：

| 字段 | 含义 |
|---|---|
| `id` | 唯一标识 |
| `title` | 一句话规则 |
| `source_failure` | **具体到题目和现象**的失败描述 |
| `observed_evidence` | 证据（日志片段、MD5 对比、对照实验数据） |
| `rule` | 规则本身 |
| `enforced_by` | 用哪些代码强制（提示词 / lint 检查） |
| `measured_effect` | **实测效果**（如 "pass@1 从 0.2 到 0.4"） |
| `validated_on` | **验证题数** |
| `status` | `effective` / `necessary-not-sufficient` / `open-limitation` |

### 3.2 现有 6 张卡（先读一遍，理解提炼方式）

| id | 内容 |
|---|---|
| `interface-contract` | 禁止凭空加 clk/rst 端口 |
| `combinational-skeleton` | 给具体骨架而非抽象规则 |
| `no-code-anchoring` | **修复提示词不要展示失败代码**（模型会照抄） |
| `structural-lint` | 仿真前做静态结构检查 |
| `seed-offset-per-attempt` | 固定 seed 会让修复完全失效 |
| `capability-limit-clock-removal` | 记录了一条**未解决限制** |

**注意最后一条**：技能包里**必须**有"这条规则没解决问题"的记录。
**全是有效结论的技能包不可信**，评审会怀疑数据真实性。

### 3.3 怎么获得真实失败样本（关键）

你需要模型服务。两种方式：

**方式一：用本机已有模型（推荐，立即可做）**

如果 Ollama 已装且有 `qwen2.5-coder:1.5b`：

```bash
export LOGICLENS_MODEL_URL="http://127.0.0.1:11434/v1"
export LOGICLENS_MODEL_NAME="qwen2.5-coder:1.5b"
export LOGICLENS_SEED=1

python3 eval.py --dataset experiments/data/verilogeval \
    --mode agent --limit 20 --samples 1 \
    --out experiments/results/analysis_run
```

**这会跑 20 道题，CPU 上约 30~60 分钟。**

**方式二：先问队友 C** 实验室机器上是否有可用的模型服务。

### 3.4 分析失败（这是提炼技能的原料）

失败样本在 `experiments/runs/eval/<题目>__s1/` 下：

```bash
# 看每道题的结果
for d in experiments/runs/eval/*__s1; do
    echo "=== $(basename $d) ==="
    python3 -c "
import json,sys
d=json.load(open('$d/result.json'))
h=(d.get('history') or [{}])[0]
print('  stage:', h.get('failed_stage'), ' type:', h.get('error_type'))
print('  lint :', h.get('lint_findings'))
"
done
```

**重点看两个东西**：
1. **生成的代码**（`$d/best.v`）——模型到底错在哪
2. **失败阶段和错误类型**——错误出在编译、仿真还是综合

### 3.5 提炼技能卡

对每一类**反复出现**的失败，写一张卡。判别标准：

- ✅ **值得写**：同一类错误在 ≥ 2 道题上出现
- ❌ **不值得写**：只出现一次的偶发错误
- ❌ **不值得写**：通用 RTL 规范（如"组合逻辑要覆盖所有分支"）——**这是"正确的废话"**，没有证据支撑

**写卡模板**：

```json
{
  "id": "简述-用连字符",
  "title": "一句话规则（祈使句）",
  "source_failure": "模型在 <具体题目> 上 <具体错误>，导致 <具体后果>",
  "observed_evidence": "<日志片段 / xvlog 报错原文 / 生成代码片段>",
  "rule": "规则本身",
  "enforced_by": ["agent/repair_policy.py 的哪一段", "agent/rtl_lint.py 的哪条检查"],
  "measured_effect": "pass@1 从 X 到 Y（<N> 道题，<配置>）",
  "validated_on": 20,
  "status": "effective"
}
```

### 3.6 建议优先挖掘的方向

我（上一轮开发者）在 5 道题上已经观察到但**未系统化**的失败模式：

| 可能的模式 | 线索 |
|---|---|
| **把数据端口当时钟沿** | 已有一张卡，但可能有更多变体（如 `always @(posedge enable)`） |
| **复位极性搞反** | `rst_n` 写成 `if (rst_n)` 而非 `if (!rst_n)` |
| **位宽截断** | 赋值时没扩展位宽，导致高位丢失 |
| **latch 推断** | 组合逻辑没用 `always @(*)` 的完整分支 |
| **恒等式表达式** | 已有一张卡（字节交换没交换），可能有其他变体 |
| **`always @(posedge clk)` 但模块无 clk** | 已有一张卡，但**未解决**——值得看更大模型是否也这样 |

### 3.7 ⚠️ 如果你想改 lint 代码

`agent/rtl_lint.py` 归**队友 B**。如果你想让某条规则变成可执行检查：

- ✅ **可以**：在 PR 里说明需求（附失败样本），由 B 或你协调实现
- ⚠️ **改之前先在群里说一声**，避免冲突

**新增 lint 规则的硬性要求**：

1. 必须有测试：**真实失败案例**做正例，**正确实现**做反例
2. findings **不得覆盖工具判定**——官方 testbench 才是正确性权威，lint 只是启发式

---

## 4. 任务 A3：补充自建题集（可选，时间够再做）

`experiments/dataset_smoke` 用于**不依赖官方数据集**的快速自检。

```bash
python3 tools/check_dataset.py experiments/dataset_smoke
```

**预期**：`Result: layout is valid.`

可以加几道覆盖边界条件的题（时钟/复位/位宽），每道题配 sidecar testbench。

---

## 5. 交付物与验收标准

| 交付物 | 验收标准 |
|---|---|
| `experiments/results/dataset_analysis.json` + 分类结论 | 156 道题全覆盖；分类维度合理；结论写在 PR 描述 |
| 20~30 道代表性题目清单 | 覆盖各题型；写在 PR 描述 |
| 一轮 20 道题的评测产出 | `experiments/results/analysis_run/` 下有 `summary.json` 和 `results.csv` |
| **技能卡扩充**（核心） | **≥ 10 张**；每张有验证题数 + 实测效果；**至少 1 张记录"无效"或"部分有效"** |

**注意**：`experiments/runs/` 和 `experiments/results/` 已被 `.gitignore` 忽略，
**不要 `git add -f`**。只提交分析脚本和技能卡。

---

## 6. 边界：**不要动**这些文件

| 文件 | 归属 | 原因 |
|---|---|---|
| `agent/controller.py` | B | 判定主路径 |
| `vivado/run_flow.tcl` | D（协调人） | **判定口径，改语义会让所有历史数据失效** |
| `agent/testbench.py` | B | 单一接口，改动影响全员 |
| `serve/`、`Dockerfile*` | C | |

**你可以动**：`experiments/data/`、`skill/`、`experiments/*.py`（新建分析脚本）

---

## 7. 提交方式

```bash
git checkout -b data/skill-cards-<你的名字>
# ... 开发 ...
python3 -m unittest discover -s tests        # 必须全绿

# ⚠️ 关键一步：用干净克隆验证
cd /tmp && git clone --branch <你的分支> --single-branch https://github.com/lsxzcd/LogicLens.git clean_check
cd clean_check && python3 -m unittest discover -s tests
# 预期 OK

git push -u origin data/skill-cards-<你的名字>
```

然后在 GitHub 开 PR。CI 会跑 3 个 Python 版本，全绿后合并。

> **为什么必须用干净克隆**：曾经有测试读取了本机存在但仓库未提交的文件，
> **本机通过、CI 直接崩**，三个检查全挂。见 `CONTRIBUTING.md`。

---

## 8. 卡住了怎么办

| 现象 | 处理 |
|---|---|
| 测试不是 `OK` | **先停下报告**，不要继续 |
| `check_parsing.py` 出现 `unexplained` | 报告，这是解析器缺陷 |
| 没有模型服务 | 先做 A1（不需要模型），同时问队友 C |
| 不确定某个失败算不算"值得写卡" | 在群里贴出失败样本和你的判断，一起定 |
| 想改 `agent/` 下任何文件 | **先在群里说** |

---

## 9. 参考文档

| 文档 | 用途 |
|---|---|
| `CONTRIBUTING.md` | 协作规范、三条铁律、干净克隆自检 |
| `docs/status-log-zh.md` | 项目全貌、已完成/未完成、22 个已修缺陷 |
| `skill/skill_cards.json` | 技能卡格式参考（**必读**） |
| `docs/task-allocation-zh.md` | 全队分工总览 |
| `REPORT.md` §5 | 技能包在报告中怎么呈现 |
