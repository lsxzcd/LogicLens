# 队友 B · 第一周任务书：智能体质量

> **这份文档可以直接转发给队友，不需要额外口头解释。**
> 有问题先看文末「卡住了怎么办」。

---

## 0. 背景（30 秒版）

我们在做一个**本地 RTL 设计智能体**（LogicLens），参加全国大学生嵌入式芯片与系统设计竞赛 AMD FPGA 赛道 RTL Track。

它做的事：**读自然语言题目 → 生成 Verilog → 用真实 Vivado 三级判定（编译/仿真/综合）→ 失败就局部修复**。

**你的方向**：提升通过率，尤其是赛题最看重的**"可综合"末级通过率**。

### 关键认知（很重要）

赛题的判定是**逐级递进**的：

```
可编译 (xvlog + xelab) → 仿真通过 (xsim 逐拍对比参考实现) → 可综合 (synth_design)
```

**只有前一级通过，才进下一级。** 所以提升通过率有两条路：

1. 让更多候选**过第一级**（编译）
2. 让过了编译的候选**真的功能正确**（仿真）

我们已有的一个工具是**结构检查器**（`agent/rtl_lint.py`），它能在**调用工具之前**发现"必然失败"的代码形状，省下一整轮工具耗时。

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
python3 tools/check_parsing.py          # 预期：... 0 unexplained
```

---

## 2. 先理解你要改的三个文件（第一天，别急着写代码）

### 2.1 `agent/rtl_lint.py` —— 结构检查器（推荐首选任务）

**它在做什么**：在把候选代码送进 Vivado **之前**，用正则检查代码形状，返回"发现列表"。

**现有 4 条规则**：

| 规则 | 检测内容 |
|---|---|
| `combinational_uses_edge` | 接口无时钟端口，却出现 `posedge`/`negedge` |
| `edge_on_non_clock_signal` | 时序题里把**非时钟端口**当时钟沿 |
| `undeclared_clock_signal` | 用作时钟沿的信号既非端口也未声明（**必然编译失败**） |
| `identity_expression` | 输出由同一输入的移位切片在相同偏移拼回 → **等于原值** |

**为什么要读它**：这类错误模型**反复犯**，而且**从源码就能判定**，不需要跑仿真。这是投入产出比最高的地方。

**读它的顺序**：
1. `Finding` 数据类
2. `lint()` 主函数（看它怎么组织规则）
3. `check_clock_edges()`（最简单，适合当模板）
4. `check_identity_expression()`（最复杂，有别名解析）

### 2.2 `agent/controller.py` —— 主流程

**读它要看懂一件事**：一轮尝试的完整顺序

```
写代码 → 【结构检查】→ 跑 Vivado 三级判定 → 通过？→ 是则结束
                                          ↓ 否
                                     生成修复提示词 → 下一轮
```

**关键细节**：
- 有 `NON_REPAIRABLE` 集合：`toolchain` 类错误**不重试**（改代码解决不了工具链问题）
- 每轮的 lint findings 会**进入修复提示词**（给模型具体的缺陷描述）
- ⚠️ **lint findings 不覆盖工具判定**——官方 testbench 才是正确性权威

### 2.3 `agent/task_parser.py` —— 规格契约解析

**它做什么**：从题面文本解析出结构化契约（端口/位宽/时钟/复位/边界）。

**当前状态**：**规则优先**，在 156 道题上 **153 道完全正确、0 处无法解释**。

**它有一个明确的缺口**（你的任务 B1）：`parse_task_with_model` 是**占位实现**。

---

## 3. 任务 B1：实现模型兜底解析（推荐第二优先）

### 3.1 现状

`agent/task_parser.py` 第 835 行：

```python
def parse_task_with_model(text: str, client) -> TaskContract:
    """Model-assisted fallback for what the rule pass could not determine."""
    contract = parse_task(text)
    if contract.ports:
        return contract
    prompt = (
        "Extract the RTL module interface as JSON. ..."
        + text
    )
    _ = (client, prompt)      # ← prompt 构建了，但从未发送给模型
    return contract
```

**问题**：`prompt` 构建了却**从未发送**，`client` 参数被丢弃（`_ = (client, prompt)` 是防未使用告警的写法）。
所以模型兜底**根本没工作**。

### 3.2 你要做的

1. **发送 prompt 给模型**：`client.generate(prompt, attempt=1)`
2. **解析返回的 JSON**：期望格式 `{"ports": [{"name": "clk", "direction": "input", "width": 1}]}`
3. **校验每一条**：
   - `direction` 必须是 `input` / `output` / `inout` 之一
   - `width` 必须是正整数
   - `name` 必须是合法 Verilog 标识符（`[A-Za-z_]\w*`）
4. **合并策略**：**只在规则没解析出来时使用模型结果**
   - 规则有 `ports` → **不调用模型**（省墙钟！）
   - 规则部分有值 → 保留规则值，只补空缺

### 3.3 硬性要求

| 要求 | 为什么 |
|---|---|
| **规则能解析时不得调用模型** | 评测时 156 道题 × 多次尝试，多一次模型调用就是纯浪费。**必须有测试证明** |
| **模型返回非法 JSON 时优雅回退** | 小模型输出不可靠，不能让它崩掉整个评测 |
| **不得覆盖规则已确定的值** | 规则解析比模型更可靠（已实测 153/156） |
| **模型输出必须结构化** | 自由文本解析不可靠 |

### 3.4 测试要求（必须写）

在 `tests/test_core.py` 加一个测试类，至少覆盖：

```python
class ModelFallbackParsingTests(unittest.TestCase):
    def test_rules_suffice_means_no_model_call(self):
        """规则能解析时，模型绝不能被调用。"""
        calls = []
        class SpyClient:
            def generate(self, prompt, attempt=1):
                calls.append(prompt)
                return "should not be called"
        text = "implement a module named TopModule with the following interface.\n - input a\n - output b\n"
        parse_task_with_model(text, SpyClient())
        self.assertEqual(calls, [], "模型被调用了，但规则本已够用")

    def test_valid_json_is_merged(self):
        """模型返回合法 JSON 时，端口被补全。"""
        ...

    def test_malformed_json_falls_back(self):
        """模型返回垃圾时不崩，回退到规则结果。"""
        ...

    def test_invalid_entries_are_rejected(self):
        """direction/width/name 非法的条目被丢弃。"""
        ...
```

**用桩客户端（stub），不要真调模型**——测试必须能在 CI 上离线跑。

### 3.5 怎么自己验证

```python
# 手动试一下
from agent.task_parser import parse_task_with_model
from agent.model_client import ModelClient

# 一个规则解析不出来的题面
text = "Design a circuit that outputs the logical AND of two signals."
client = ModelClient(url="http://127.0.0.1:11434/v1", model="qwen2.5-coder:1.5b")
print(parse_task_with_model(text, client).to_dict())
```

---

## 4. 任务 B2：扩充结构检查器（推荐第三优先，可与 A 配合）

### 4.1 候选规则（按可行性排序）

| 规则 | 检测内容 | 难度 |
|---|---|---|
| `latch_inference` | 组合逻辑 `always` 块里某分支没赋值 → 综合推断 latch | 中 |
| `multiple_driver` | 同一信号被 `assign` 和 `always` 同时驱动 | 低 |
| `reset_polarity` | `rst_n`（低有效）却写成 `if (rst_n)` | 中 |
| `width_truncation` | 赋值时位宽收窄且无显式截断 | 中 |
| `unconnected_output` | 声明的输出端口从未被赋值 | 低 |

### 4.2 硬性要求

1. **每条新规则必须有测试**，且用**真实失败案例**做正例、**正确实现**做反例
2. **不得误报**：宁可漏检，不可误判——误报会让正确设计被"提示"改坏
3. findings **不得覆盖工具判定**（沿用现有设计）
4. 新规则的 `Finding.rule` 名字要**描述现象**，不要描述原因

### 4.3 测试模板

```python
def test_latch_inference_is_flagged(self):
    # 组合逻辑 if 没有 else → 推断 latch
    rtl = """
module TopModule (input wire a, input wire b, output reg y);
    always @(*) begin
        if (a) y = b;
    end
endmodule"""
    rules = {f.rule for f in lint(rtl, parse_task(self.SOMETASK))}
    self.assertIn("latch_inference", rules)

def test_complete_assignment_is_clean(self):
    rtl = """
module TopModule (input wire a, input wire b, output reg y);
    always @(*) begin
        if (a) y = b;
        else   y = 1'b0;
    end
endmodule"""
    self.assertEqual(lint(rtl, parse_task(self.SOMETASK)), [])
```

⚠️ **测试数据要自带**，不要读 `experiments/data/` 下的题目文件——
那些文件**大部分没提交到仓库**（只有 7 道），会让测试在 CI 上崩。见文末。

---

## 5. 任务 B3：多候选生成与打分（**风险较高，先别做**）

当前是**单候选串行重试**。改造成多候选可以提升单次成功概率，但：

- 直接影响**墙钟**（赛题占 10 分）
- 与判定口径相邻
- 需要先小规模验证

**建议**：等 B1/B2 完成、评测流程稳定后再动。如果你想做，**先在群里讨论方案**。

---

## 6. 交付物与验收标准

| 交付物 | 验收标准 |
|---|---|
| **B1 模型兜底解析** | 规则可解析时**不调用模型**（有测试证明）；非法 JSON 优雅回退；不覆盖规则值 |
| **B2 结构检查扩充** | ≥ 2 条新规则；每条有正例+反例测试；无 CI 失败 |
| 单元测试 | **全部通过**，且不依赖外部服务（可在 CI 离线跑） |
| 干净克隆验证 | 见下方「提交方式」 |

---

## 7. ⚠️ 一个必须知道的坑（我们真的踩过）

**测试不要依赖未提交的文件。**

`experiments/data/verilogeval/` 全量有 **156 道题**，但仓库**只跟踪 7 道**——
因为全量用一条命令就能重建，不该塞进 Git 历史。

**后果**：如果你的测试读了某道**未提交**的题目，它会：
- ✅ 在你本机通过（你有全量导出）
- ❌ 在 CI 上 **`FileNotFoundError`，3 个检查全挂**

**正确做法（二选一）**：

1. **测试自带数据**——把题面直接写在测试里（推荐）
2. **必须读 fixture 时加跳过保护**：

```python
if not self.prompt.is_file():
    self.skipTest("fixture not present; run tools/fetch_verilogeval_problem.py")
```

已提交的 7 道题：`Prob001_zero`、`Prob090_circuit1`、`Prob100_fsm3comb`、
`Prob104_mt2015_muxdff`、`Prob120_fsm3s`、`Prob131_mt2015_q4`、`Prob156_review2015_fancytimer`。

---

## 8. 边界：**不要动**这些文件

| 文件 | 归属 | 原因 |
|---|---|---|
| `vivado/run_flow.tcl` | D（协调人） | **判定口径**。改语义会让所有历史数据和 `REPORT.md` 失效 |
| `agent/testbench.py` | B（你） | ⚠️ 单一接口，改动影响全员——**改前先在群里说** |
| `agent/controller.py` | B（你） | ⚠️ 主路径，**改前先在群里说** |
| `skill/skill_cards.json` | A | 技能卡归 A |
| `serve/`、`Dockerfile*` | C | |

**你可以放心动**：`agent/rtl_lint.py`、`agent/task_parser.py`、`tests/test_core.py`

**同时只允许一人改 `agent/controller.py`。**

---

## 9. 提交方式

```bash
git checkout -b feat/<你的任务>-<你的名字>     # 如 feat/lint-rules-b
# ... 开发 ...
python3 -m unittest discover -s tests          # 必须全绿

# ⚠️ 关键一步：用干净克隆验证
cd /tmp && git clone --branch <你的分支> --single-branch https://github.com/lsxzcd/LogicLens.git clean_check
cd clean_check && python3 -m unittest discover -s tests
# 预期 OK

git push -u origin feat/<你的任务>-<你的名字>
```

然后开 PR。CI 跑 3 个 Python 版本，全绿后合并。

---

## 10. 卡住了怎么办

| 现象 | 处理 |
|---|---|
| 测试不是 `OK` | **先停下报告**，不要继续 |
| 需要真实模型才能测 | 用**桩客户端**（stub），测试必须离线可跑 |
| 想改 `agent/controller.py` | **先在群里说**，避免与别人冲突 |
| 不确定新 lint 规则会不会误报 | 在群里贴出正例和反例，一起判断 |
| 想做的规则正则写不出来 | 先只做低难度的（`unconnected_output`、`multiple_driver`），别硬啃 |

---

## 11. 参考文档

| 文档 | 用途 |
|---|---|
| `CONTRIBUTING.md` | 协作规范、三条铁律、干净克隆自检 |
| `docs/status-log-zh.md` | 项目全貌、22 个已修缺陷（**看这些能理解哪些坑已填**） |
| `skill/skill_cards.json` | 6 张技能卡，含实测效果——理解"什么算证据" |
| `REPORT.md` §4 | 智能体设计在报告中怎么呈现 |
| `agent/rtl_lint.py` | **你的主要工作面，先通读** |
