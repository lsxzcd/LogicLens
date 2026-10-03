$ErrorActionPreference = "Stop"

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $pythonLauncher) {
    throw "Python Launcher (py.exe) was not found. Install Python 3.11 or newer."
}

& $pythonLauncher.Source -3 run.py `
    --question data/examples/counter/question.txt `
    --mock `
    --run-dir experiments/runs/smoke_agent

& $pythonLauncher.Source -3 ui/generate_report.py `
    experiments/runs/smoke_agent/result.json `
    --output experiments/runs/smoke_agent/report.html

Write-Host "LogicLens mock run completed."
Write-Host "Report: experiments/runs/smoke_agent/report.html"

