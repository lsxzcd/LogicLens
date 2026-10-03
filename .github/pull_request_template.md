<!--
PR 模板：GitHub 会自动把它填进每个新建 Pull Request 的描述里。
目的是让评审者不用追问就能判断"这个改动能不能合"。
-->

## 这个 PR 做了什么

<!-- 一到三句话说明改动内容和动机 -->

## 影响范围

- [ ] 只改文档 / 配置（无判定口径变化）
- [ ] 改到三级判定口径（`vivado/run_flow.tcl` 或结果字段）
- [ ] 改到规格契约字段（`agent/task_parser.py`）
- [ ] 改到测试台获取逻辑（`agent/testbench.py`）
- [ ] 新增数据集 / 测试台 / 参考答案

## 自检（提交前请全部完成）

- [ ] `py -3 -m unittest discover -s tests` 全绿
- [ ] `py -3 tools/check_architecture.py` 通过
- [ ] 若改到判定流程：`py -3 experiments\p05_verify.py` 无 failed assertion
- [ ] 若改到测试台：`py -3 experiments\tb_verify.py` 无 failed case
- [ ] 若改到端到端链路：`py -3 experiments\pipeline_verify.py` 无 failed case

## 判定口径变更说明

<!--
如果勾选了上面任一"改到判定口径/契约字段"的选项，请在这里说明：
1. 改了哪个字段的语义；
2. 为什么必须改；
3. 对已产出的实验数据有什么影响（是否需要重跑）。
口径变更必须同步更新 CONTRIBUTING.md 的字段表，否则评审者无法判断历史数据是否可比。
-->

## 实验数据

<!--
如有真实实验结果，请贴出对比表，并注明：
- 数据集与题量、samples 数；
- 是否为 --mock（--mock 结果禁止写入 REPORT.md 结论）。
-->
