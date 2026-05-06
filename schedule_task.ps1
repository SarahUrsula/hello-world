# Registers a Windows Scheduled Task that runs run_checker.bat every 10 minutes.
# Run this once from an elevated PowerShell (Run as Administrator).
#
#   powershell -ExecutionPolicy Bypass -File schedule_task.ps1

$TaskName = "Otter Trail Checker"
$ScriptDir = $PSScriptRoot
$BatPath = Join-Path $ScriptDir "run_checker.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "run_checker.bat not found at $BatPath"
    exit 1
}

# Action: run the .bat file, working directory set so state.json lands here
$action = New-ScheduledTaskAction `
    -Execute $BatPath `
    -WorkingDirectory $ScriptDir

# Trigger: every 10 minutes, indefinitely, starting now
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration ([TimeSpan]::MaxValue)).Repetition

# Settings: don't run if on battery, allow new instance to skip if previous still running
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

# Run as the current user, only when logged in (avoids password prompt + still works headless)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

# Replace any existing task with the same name
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Checks SANParks Otter Trail availability every 10 minutes"

Write-Host ""
Write-Host "Scheduled '$TaskName' to run every 10 minutes."
Write-Host "  Script:  $BatPath"
Write-Host "  Logs to: $(Join-Path $ScriptDir 'checker.log')"
Write-Host ""
Write-Host "View in Task Scheduler (taskschd.msc) or run:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "To remove later:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
