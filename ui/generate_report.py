from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    output = args.output or args.result.with_suffix(".html")
    rows = []
    for item in result.get("history", []):
        rows.append(
            "<tr>"
            f"<td>{item.get('attempt')}</td>"
            f"<td>{html.escape(str(item.get('error_type', '')))}</td>"
            f"<td>{'PASS' if item.get('compile_pass') else 'FAIL'}</td>"
            f"<td>{'PASS' if item.get('elaborate_pass') else 'FAIL'}</td>"
            f"<td>{'PASS' if item.get('simulation_pass') else 'FAIL'}</td>"
            f"<td>{'PASS' if item.get('synthesis_pass') else 'FAIL'}</td>"
            f"<td>{'PASS' if item.get('timing_constraint_pass') else 'FAIL'}</td>"
            f"<td>{item.get('elapsed_seconds', 0)} s</td>"
            "</tr>"
        )
    page = f"""<!doctype html>
<html lang='zh-CN'><meta charset='utf-8'><title>LogicLens run report</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:36px;background:#f6f7fb;color:#202124}}
.card{{background:white;border-radius:12px;padding:20px;margin:14px 0;box-shadow:0 2px 12px #0001}}
h1{{color:#5b176f}} table{{border-collapse:collapse;width:100%}} th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}
.pass{{color:#138a42;font-weight:bold}} .fail{{color:#c62828;font-weight:bold}}
</style>
<body><h1>LogicLens 运行报告</h1>
<div class='card'><b>模式：</b>{html.escape(str(result.get('mode')))}<br>
<b>最终结果：</b><span class='{ 'pass' if result.get('success') else 'fail' }'>{'PASS' if result.get('success') else 'FAIL'}</span><br>
<b>最佳尝试：</b>{result.get('best_attempt')}<br>
<b>总耗时：</b>{result.get('elapsed_seconds', 0)} s</div>
<div class='card'><h2>验证过程</h2><table><tr><th>尝试</th><th>错误类别</th><th>编译</th><th>展开</th><th>仿真</th><th>综合</th><th>5 ns 约束</th><th>耗时</th></tr>{''.join(rows)}</table></div>
</body></html>"""
    output.write_text(page, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
