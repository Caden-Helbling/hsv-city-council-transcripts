# elevated-transcribe-daily.ps1 - move the whisper task from weekly to daily.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\elevated-transcribe-daily.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\elevated-transcribe-daily.ps1 -Revert
#
# Must run ELEVATED: once elevated-transcribe-s4u.ps1 has converted the task to
# an S4U principal, Set-ScheduledTask on it returns Access Denied from a normal
# session. Nothing here makes the task itself elevated - it stays caden at
# RunLevel Limited, and this script does not touch the principal at all.
#
# WHY DAILY
#
# The task ran Fridays 8 PM, chosen for a council that meets Thursday evenings.
# But the archive also picks up work sessions and special sessions on other
# days, and audio only becomes transcribable once the sync workflow has
# published the release asset. So a meeting on any day but Thursday could wait
# most of a week: the 2026-09-18 work session is a Friday 11 AM meeting, whose
# audio lands after the Friday 08:00 CT sync and therefore after the 8 PM
# window that same day - a 7-day wait for its transcript.
#
# Daily costs almost nothing because the task no-ops when nothing is pending:
# D:\llm\logs\transcribe-council.log shows those runs finishing in one second
# with llama-server untouched ("nothing pending; llama-server untouched"). The
# LLM stack is still only stopped when there is real work, which is the same
# 2-4 times a month as before - just sooner after the meeting.
#
# ASCII only in this file: PowerShell 5.1 reads .ps1 as ANSI without a BOM.

param([switch]$Revert)

$ErrorActionPreference = 'Stop'
$TaskName = 'HSV council whisper transcription'

function Say($msg) { Write-Output ('  ' + $msg) }

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error ('Run this elevated. Editing an S4U task needs admin; ' +
        'a normal session gets Access Denied from Set-ScheduledTask.')
    exit 1
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Error ("No task named '$TaskName'. Register it first: " +
        'powershell -File scripts\transcribe-council.ps1 -Register')
    exit 1
}

$before = ($task.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ', '
Say "current trigger: $before"
Say ('current principal: {0} / {1} (left untouched)' -f `
    $task.Principal.LogonType, $task.Principal.UserId)

if ($Revert) {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 8pm
    $want = 'MSFT_TaskWeeklyTrigger'
    $label = 'weekly, Fridays 8 PM'
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At 8pm
    $want = 'MSFT_TaskDailyTrigger'
    $label = 'daily, 8 PM'
}

Set-ScheduledTask -TaskName $TaskName -Trigger $trigger | Out-Null

# Verify from a fresh read rather than trusting the call: confirm the trigger
# changed AND that the principal survived, since a botched principal is the
# failure that would silently stop the task from firing logged out.
$after = Get-ScheduledTask -TaskName $TaskName
$actual = ($after.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ', '
$info = $after | Get-ScheduledTaskInfo

$ok = $true
if ($actual -ne $want) { Say "FAIL: trigger is '$actual', wanted '$want'"; $ok = $false }
if ($after.Principal.LogonType -ne $task.Principal.LogonType) {
    Say ('FAIL: principal changed from {0} to {1}' -f `
        $task.Principal.LogonType, $after.Principal.LogonType)
    $ok = $false
}
if (-not $ok) { exit 1 }

Say "trigger -> $label"
Say ('principal still {0} / {1}' -f $after.Principal.LogonType, $after.Principal.UserId)
Say ('next run: {0}' -f $info.NextRunTime)
Write-Output ''
Write-Output "OK: '$TaskName' now runs $label."
Write-Output 'It no-ops in about a second when no meeting needs transcribing.'
exit 0
