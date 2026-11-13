chcp 65001 > $null
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'SpiritScout console :8010 (local model qwen-coder-7b)'
# 工作区用 configs/system.yaml 的 workspace.root（SpiritScout\.spiritscout）。
# 之前用 SPIRITSCOUT_WORKSPACE__ROOT 指到 _work\agent-test\ws（8015 那套测试数据），
# 结果经验/用量分成了两套库；现已合并回 .spiritscout，不再覆盖。
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'
$env:PYTHONFAULTHANDLER = '1'
$env:PYTHONUNBUFFERED = '1'
Set-Location 'C:\Users\admin\Desktop\全自动打靶\SpiritScout'
Write-Host 'SpiritScout console - local model only, no cloud (log tee: _work\agent-server.log)' -ForegroundColor Cyan
& '.\.venv\Scripts\python.exe' -X faulthandler -X utf8 -m spiritscout --config configs\system.yaml --port 8010 2>&1 |
  Tee-Object -FilePath 'C:\Users\admin\Desktop\全自动打靶\_work\agent-server.log'
# python 退出（正常停止/被杀/崩溃）后窗口直接关掉，不留一个只有提示符的空壳——
# 重启时旧窗口残留成「弹出来什么都没干」的样子。运行中窗口照常显示日志。
Write-Host "[退出] 服务已结束（退出码 $LASTEXITCODE），窗口即将关闭" -ForegroundColor Yellow
Start-Sleep -Seconds 3
exit $LASTEXITCODE
