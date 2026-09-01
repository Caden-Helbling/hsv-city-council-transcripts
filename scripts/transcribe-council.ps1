# transcribe-council.ps1 - scheduled Whisper transcription for the council archive.
#
# Runs weekly (Friday 8 PM, after the morning sync has published audio release
# assets) as a non-elevated Interactive scheduled task on slayden. Safe to run
# any time:
#   - exits immediately when no meeting needs transcription (llama-server untouched)
#   - stops llama-server only for the transcription window; restart is in finally
#   - commits + pushes transcripts, which triggers the site deploy
#
# Registration (one-time, non-elevated - see README "Automation"):
#   powershell -File scripts\transcribe-council.ps1 -Register
#
# ASCII only in this file: PowerShell 5.1 reads .ps1 as ANSI without a BOM.

param([switch]$Register)

$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\caden\code\hsv-city-council-transcripts'
$logDir = 'D:\llm\logs'
$logFile = Join-Path $logDir 'transcribe-council.log'
$errFile = Join-Path $logDir 'transcribe-council.stderr.txt'

if ($Register) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $repo + '\scripts\transcribe-council.ps1"')
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 8pm
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    Register-ScheduledTask -TaskName 'HSV council whisper transcription' `
        -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output 'Registered task: HSV council whisper transcription (Fridays 8 PM)'
    exit 0
}

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
function Log($msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $logFile -Value $line -Encoding utf8
    Write-Output $line
}

# NOTE: no 2>&1 on native commands anywhere in this script - under
# ErrorActionPreference=Stop, PS 5.1 wraps redirected native stderr in
# NativeCommandError and a routine git/whisper progress line would abort the run.
#
# But discarding stderr made a real failure undiagnosable: on 2026-08-28 whisper
# failed 55s into the 2026-08-27 meeting and the log recorded only
# 'WARN: transcribe reported failures' - hsvcc.py prints the reason to stderr, so
# the reason was gone and the failure could not be reproduced afterwards. So the
# redirect is handed to cmd.exe instead: cmd does the 2> itself, PowerShell only
# ever sees stdout, and the captured stderr is appended to the log on failure.
# python runs -u so stdout is unbuffered and progress lines land as they happen
# rather than being lost in the pipe buffer when a run dies.
# Sets $script:LastRunExit rather than returning the code: Log writes to the
# pipeline via Write-Output, so a 'return $code' hands back every logged line
# with the code appended, and the caller's '-ne 0' then tests an array.
function Invoke-Logged($argline) {
    if (Test-Path $errFile) { Remove-Item $errFile -Force }
    cmd /c "python -u $argline 2>`"$errFile`"" | ForEach-Object { Log $_ }
    $script:LastRunExit = $LASTEXITCODE
    if ($script:LastRunExit -ne 0 -and (Test-Path $errFile)) {
        Get-Content $errFile | Where-Object { $_.Trim() } |
            ForEach-Object { Log ('  stderr: ' + $_) }
    }
}
try {
    Set-Location $repo
    Log 'run start'
    git pull --rebase | Out-Null

    $pendingScript = 'import json, pathlib; ' +
        "root = pathlib.Path(r'$repo') / 'meetings'; " +
        '[print(d.name) for d in sorted(root.iterdir()) ' +
        "if (d / 'meeting.json').exists() " +
        "and json.loads((d / 'meeting.json').read_text())['status'].get('has_audio_asset') " +
        "and not json.loads((d / 'meeting.json').read_text())['status'].get('has_whisper')]"
    $pending = @(python -c $pendingScript)
    if ($pending.Count -eq 0) {
        Log 'nothing pending; llama-server untouched'
        exit 0
    }
    Log ('pending: ' + ($pending -join ', '))

    Invoke-Logged 'scripts\hsvcc.py fetch-audio --all-pending'
    if ($script:LastRunExit -ne 0) { Log 'WARN: fetch-audio reported failures' }

    Log 'stopping llama-server (frees VRAM for whisper)'
    Stop-Service llama-server -Force
    try {
        Invoke-Logged 'scripts\hsvcc.py transcribe --all-pending'
        if ($script:LastRunExit -ne 0) {
            Log 'WARN: transcribe reported failures (stderr above)'
        }
    } finally {
        Log 'restarting llama-server + open-webui'
        Start-Service llama-server
        Start-Service open-webui
    }

    git add meetings/
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m 'chore: whisper transcripts (scheduled)' | Out-Null
        git pull --rebase origin main | Out-Null
        git push | Out-Null
        Log 'transcripts committed and pushed'
    } else {
        Log 'no transcript changes to commit'
    }
    Log 'run complete'
} catch {
    Log ('ERROR: ' + $_.Exception.Message)
    exit 1
}
