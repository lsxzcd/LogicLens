# 模型配置（MODEL.md）

赛题要求声明模型的**来源、版本、量化方式、显存占用、上下文配置**（选题指南 3.1.5.1）。
本文档分两部分：**已确认的事实**与**待 AMD 机器实测的字段**。

> 生成方式：`size_vram`、量化、摘要等都由服务上报，不要手抄。
> ```bash
> python3 serve/record_service.py --model <模型名> --write model/service-measurements.json
> ```

---

## 一、当前状态（重要）

**正式评测模型尚未确定**，因为选型受显存约束，而本机没有独立显卡。

| 项目 | 现状 |
|---|---|
| 本机用于验证的模型 | `qwen2.5-coder:1.5b`，CPU 推理 |
| 用途 | **仅验证软件链路与技能包规则有效性** |
| **能否作为赛题结果** | ❌ **不能**——未证明 GPU 驻留，且 1.5B 能力不足以代表方案水平 |

本机实测（`size_vram = 0` 说明未驻留显存）：

| 字段 | 值 |
|---|---|
| 服务版本 | Ollama 0.40.2 |
| 量化 | `Q4_K_M` |
| 权重文件大小 | 986.1 MB |
| 驻留内存 | 1170.0 MB |
| **驻留显存** | **n/a（未证明 GPU 驻留）** |
| 模型上下文长度 | 32768 |
| 加载上下文长度 | 4096 |
| 推理后端 | `llamacpp` |

---

## 二、推理后端

| 项目 | 值 |
|---|---|
| 后端 | **Ollama**（OpenAI 兼容 HTTP 接口，`/v1/chat/completions`） |
| 选择理由 | 单一二进制、无 Python 依赖、原生支持 AMD GPU（ROCm）与 Vulkan 回退 |
| 接口版本 | OpenAI chat completions（`choices[0].message.content`） |
| 服务配置与启动脚本 | `serve/`，见 `serve/README-zh.md` |
| 备选后端 | llama.cpp server、vLLM——均兼容同一接口，换后端只改 `LOGICLENS_MODEL_URL` |

**换后端的成本**：只改环境变量，无需改代码。

> AMD 机器提示：GitHub 发布页有 **`ollama-windows-amd64-rocm.zip`（仅 255 MB）**，
> 相比 1.5 GB 的完整安装包小得多：
> https://github.com/ollama/ollama/releases

---

## 三、采样与上下文配置

`run.sh` 与 `run_baseline.sh` **必须使用完全相同的配置**，否则报告的增益无法归因于智能体。

| 参数 | 值 | 环境变量 | 说明 |
|---|---|---|---|
| temperature | 0.2 | `LOGICLENS_TEMPERATURE` | 低温以偏向确定性 |
| top_p | 0.95 | `LOGICLENS_TOP_P` | |
| max_tokens | 2048 | `LOGICLENS_MAX_TOKENS` | 单次输出上限 |
| seed 基数 | 1 | `LOGICLENS_SEED` | **实际发送 `seed + attempt - 1`**，见下 |
| 上下文长度 | 4096（加载值） | 后端参数 | 模型支持 32768，实际按 4096 加载 |
| 系统提示词 | RTL Verilog 工程师，要求简洁可综合 | `LOGICLENS_SYSTEM_PROMPT` | |
| 请求超时 | 300 s | `LOGICLENS_TIMEOUT` | 首次请求含模型加载，明显更慢 |

### 为什么 seed 要按尝试次数偏移

本地服务在**固定 seed 下完全确定**——实测连提高 temperature 都不能改变输出
（同一请求重复 3 次，`seed=1` 在 temperature 0.2 和 0.8 下都只得到 1 种输出；去掉 seed 后得到 2 种）。

因此如果每次修复都发同一个 seed，修复循环会拿到**逐字节相同**的错误代码，三次重试全部浪费。
现在发送 `seed + (attempt - 1)`：**整个运行仍可复现**，但修复能够产生新代码。

---

## 四、待实测字段（必须在 AMD 机器上填）

| 字段 | 怎么得到 | 为什么必须在 AMD 机器上做 |
|---|---|---|
| **模型仓库地址 + 版本/权重摘要** | `ollama show <模型>` 或 `record_service.py` 的 `digest` | 选定模型后才知 |
| **量化方式** | `record_service.py` 的 `quantization` | 同上 |
| **实测显存占用** | `record_service.py` 的 **`size_vram`** | **本机为 0（无独显）；赛题要求"单卡 32 GB 内"，必须真实测量** |
| **上下文长度与最大输出** | `record_service.py` 的 `context_length_loaded` | 需在目标机器确认 |
| **是否微调** | 当前：**未微调** | 若微调，权重须开源并在提交物中声明 |

### 选型约束（赛题硬指标）

> 模型须能在**单张 32 GB 显卡**上完整容纳，**不允许跨卡**。

按显存粗估（详细对照见 `docs/amd-machine-validation-zh.md` §2）：

| 显存 | 可行量级 | 示例 |
|---|---|---|
| 32 GB | 7B（FP16）或 32B（Q4） | `qwen2.5-coder:32b` Q4_K_M ≈ 20 GB |
| 48 GB（W7900） | 32B 可上更高量化 | Q6/Q8 ≈ 27~35 GB |

**填表检查清单**（AMD 机器上）：

- [ ] `python3 serve/record_service.py --model <模型> --json` → `size_vram > 0`
- [ ] `size_vram` 换算后 **< 32 GB** → 满足单卡约束
- [ ] 与 `docs/amd-machine-validation-zh.md` §2 的选型表核对
- [ ] 把数值填入本文件 §1 的表格
- [ ] 确认 `run.sh` 与 `run_baseline.sh` 采样配置一致

---

## 五、环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `LOGICLENS_MODEL_URL` | 无（必须设置） | 基础 URL 或完整 chat-completions URL 都接受 |
| `LOGICLENS_MODEL_NAME` | `local-coder-model` | 请求中发送的模型名 |
| `LOGICLENS_API_KEY` | 空 | 仅当后端需要鉴权；本地部署通常为空 |
| `LOGICLENS_TEMPERATURE` | 0.2 | |
| `LOGICLENS_TOP_P` | 0.95 | |
| `LOGICLENS_MAX_TOKENS` | 2048 | |
| `LOGICLENS_SEED` | 未设置 | 设置后启用按尝试偏移 |
| `LOGICLENS_TIMEOUT` | 300 | 秒 |
| `LOGICLENS_RETRIES` | 2 | 传输错误与 5xx 的重试次数；4xx 不重试 |
| `LOGICLENS_SYSTEM_PROMPT` | 内置 | 覆盖系统提示词 |
| `OLLAMA_MODELS` | `/models`（容器内） | 权重目录；本机为 `D:\JZDSLx\ollama_models` |

完整模板见 `serve/env.example`。

---

## 六、验证与诚实说明

| 结论 | 证据 |
|---|---|
| 无图形界面下模型可用 | `tools/check_model.py` → `OK replied in 2.05s` |
| 服务配置可被自动记录 | `serve/record_service.py` 输出全部字段 |
| 采样配置写入结果 JSON，可复现 | 结果文件的 `model` 字段 |
| 固定 seed 的确定性（及危害） | `skill/skill_cards.json` 的 `seed-offset-per-attempt` 卡 |
| **真实显存占用** | ❌ **未验证**——本机无独显 |
| **所选模型满足单卡 32 GB** | ❌ **未验证**——依赖 AMD 机器 |
| **本文档的数据来自真实评测模型** | ❌ **不是**——本项目前只用于链路验证 |

⚠️ **在 AMD 机器上完成 §4 之前，本文档不得作为最终提交版本。**
