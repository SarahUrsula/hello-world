# Registers a Windows Scheduled Task with targeted daily run times:
#   Morning cluster (when SANParks typically releases new slots):
#     08:00, 08:15, 08:30, 08:45, 09:00, 09:15
#   Afternoon checks:
#     13:00, 17:00
#
# Run this once from an elevated PowerShell (Run as Administrator):
#   powershell -ExecutionPolicy Bypass -File schedule_task.ps1

$TaskName = "Otter Trail Checker"
$ScriptDir = $PSScriptRoot
$BatPath = Join-Path $ScriptDir "run_checker.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "run_checker.bat not found at $BatPath"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $BatPath `
    -WorkingDirectory $ScriptDir

# Build one daily trigger per run time
$runTimes = @("08:00", "08:15", "08:30", "08:45", "09:00", "09:15", "13:00", "17:00")
$triggers = $runTimes | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At $_
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

# Run as the current user, only when logged in
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Checks SANParks Otter Trail availability (morning cluster + afternoon checks)"

Write-Host ""
Write-Host "Scheduled '$TaskName' with the following daily run times:"
foreach ($t in $runTimes) { Write-Host "  $t" }
Write-Host ""
Write-Host "  Script:  $BatPath"
Write-Host "  Logs to: $(Join-Path $ScriptDir 'checker.log')"
Write-Host ""
Write-Host "To remove later:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
