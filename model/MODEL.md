# Model configuration

当前代码通过 OpenAI-compatible HTTP 接口调用本地模型。

请在正式实验前补充：

- 模型仓库地址和版本；
- 推理后端；
- 量化方式；
- 实测显存占用；
- 上下文长度和最大输出长度；
- 是否进行微调。

环境变量：

- `LOGICLENS_MODEL_URL`
- `LOGICLENS_MODEL_NAME`
- `LOGICLENS_API_KEY`（可选）

