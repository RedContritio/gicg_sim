# DMC training status — Windows side. Called by Mac tools/runs/status.py.
# Args:
#   $args[0] = optional run dir name (default: latest *_dmc_* under artifacts)

param([string]$RunName = '')

$ErrorActionPreference = 'SilentlyContinue'

$latest = $null
if ($RunName) {
  $latest = Get-ChildItem 'D:\gicg_dev\artifacts' -Directory | Where-Object Name -Eq $RunName | Select-Object -First 1
}
if (-not $latest) {
  $latest = Get-ChildItem 'D:\gicg_dev\artifacts' -Directory | Where-Object Name -Match '_dmc_' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

if ($latest) { Write-Output ("===RUN===" + $latest.Name) }
else { Write-Output "===RUN===(none)" }

Write-Output '===GPU==='
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader

Write-Output '===MEM==='
# Fallback chain: Win32_OperatingSystem → Get-Counter \Memory\Available MBytes →
# sum of process WorkingSet (rough lower bound).
$mem_pct = $null
$os = Get-CimInstance Win32_OperatingSystem
if ($os) {
  $mem_used_mb = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1024, 0)
  $mem_total_mb = [math]::Round($os.TotalVisibleMemorySize/1024, 0)
  $mem_pct = [math]::Round((1 - $os.FreePhysicalMemory/$os.TotalVisibleMemorySize) * 100, 1)
  Write-Output ("mem_used=" + $mem_used_mb + "MB total=" + $mem_total_mb + "MB pct=" + $mem_pct + "%")
} else {
  # Fallback: sum WorkingSet across all processes (rough used; doesn't see total).
  $sum_ws = (Get-Process | Measure-Object -Property WorkingSet -Sum).Sum
  if ($sum_ws) {
    Write-Output ("mem_used~=" + [math]::Round($sum_ws/1MB, 0) + "MB (sum WorkingSet, no total)")
  } else {
    Write-Output "mem_unavailable"
  }
}

Write-Output '===CPU==='
# Sample-based CPU%: 2 Get-Process snapshots ~0.8s apart, no admin needed.
$t1 = Get-Date
$cpu1 = (Get-Process | Measure-Object -Property CPU -Sum).Sum
Start-Sleep -Milliseconds 800
$t2 = Get-Date
$cpu2 = (Get-Process | Measure-Object -Property CPU -Sum).Sum
$elapsed = ($t2 - $t1).TotalSeconds
$cpu_cores = [Environment]::ProcessorCount
if ($elapsed -gt 0 -and $cpu_cores -gt 0) {
  $cpu_pct = [math]::Round((($cpu2 - $cpu1) / $elapsed / $cpu_cores) * 100, 1)
  Write-Output ("cpu_pct=" + $cpu_pct + "% cores=" + $cpu_cores)
}

Write-Output '===PROC==='
Get-Process python | ForEach-Object {
  Write-Output ('python pid=' + $_.Id + ' cpu_s=' + [math]::Round($_.CPU, 1) + ' ws_mb=' + [math]::Round($_.WorkingSet/1MB, 1))
}

Write-Output '===METRICS==='
if ($latest) {
  $mf = Join-Path $latest.FullName 'metrics.jsonl'
  if (Test-Path $mf) {
    Get-Content $mf | Select-Object -Last 30 | ForEach-Object { $_ }
  }
}
