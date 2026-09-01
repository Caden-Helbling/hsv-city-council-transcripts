# elevated-transcribe-s4u.ps1 - run the whisper transcription task logged out.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\elevated-transcribe-s4u.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\elevated-transcribe-s4u.ps1 -Revert
#
# Must run ELEVATED. Registering an S4U principal and editing a service ACL both
# require admin; nothing else about the task becomes elevated - it keeps running
# as caden at RunLevel Limited.
#
# WHY
#
# 'HSV council whisper transcription' runs Fridays 8 PM as an Interactive task,
# so it only fires while caden is signed in. StartWhenAvailable means a logged-off
# Friday is not lost - it runs at the next logon instead - but that pulls the LLM
# stack down at an unpredictable moment rather than a known 8 PM window. S4U
# ("whether logged on or not", no stored password) is what the other four tasks
# on this box already use.
#
# TWO THINGS BREAK IF YOU ONLY FLIP THE PRINCIPAL
#
# 1. Service rights. llama-server's ACL grants start/stop to IU - Interactive
#    Users, S-1-5-4 - which is how the task stops it without admin. An S4U token
#    is a BATCH logon and carries no S-1-5-4, so Stop-Service would fail Access
#    Denied, and whisper would then run against a GPU llama-server still owns and
#    OOM. This script adds an ACE for the caden account itself.
#
# 2. git push. The repo uses credential.helper=manager, and GCM keeps the token
#    DPAPI-encrypted under caden's profile. S4U has no password-derived DPAPI
#    master key, so the push at the end of a run would fail. The repo therefore
#    has to be on an SSH remote (plain key file, readable under S4U - the same
#    reason the NAS backup task works) BEFORE this conversion is worth doing.
#    This script refuses to proceed until that is true.
#
# HOW IT VERIFIES
#
# Checking the ACL from this elevated shell would prove nothing - admin already
# has full rights. So after converting, it registers a throwaway probe task under
# the SAME S4U principal, and that probe does the real work: stop llama-server,
# start it back, and run git ls-remote. If either fails, the principal and the
# ACL are rolled back and the script exits nonzero.
#
# ASCII only in this file: PowerShell 5.1 reads .ps1 as ANSI without a BOM.

param([switch]$Revert)

$ErrorActionPreference = 'Stop'

$TaskName = 'HSV council whisper transcription'
$Service  = 'llama-server'
$Repo     = 'C:\Users\caden\code\hsv-city-council-transcripts'
$Account  = "$env:COMPUTERNAME\caden"
$ProbeName = 'ZZ hsv s4u verification probe'
$ProbeDir  = Join-Path $env:TEMP 'hsv-s4u-probe'

function Say($msg) { Write-Output ('  ' + $msg) }

# ---------------------------------------------------------------- preconditions

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'This script must run elevated (Run as administrator).'
    exit 1
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Error "Scheduled task not found: $TaskName"; exit 1 }

$sid = (New-Object Security.Principal.NTAccount($Account)).Translate(
           [Security.Principal.SecurityIdentifier]).Value
$aceForCaden = "(A;;CCLCSWRPWPDTLOCRRC;;;$sid)"

function Get-ServiceSddl {
    $raw = (sc.exe sdshow $Service) -join ''
    return ($raw -replace '\s', '')
}

function Set-ServiceSddl($sddl) {
    $out = sc.exe sdset $Service $sddl
    if ($LASTEXITCODE -ne 0) { throw ("sc sdset failed: " + ($out -join ' ')) }
}

# ------------------------------------------------------------------- revert path

if ($Revert) {
    Write-Output "Reverting '$TaskName' to Interactive and dropping the added ACE."
    $p = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Limited
    Set-ScheduledTask -TaskName $TaskName -Principal $p | Out-Null
    Say 'principal -> Interactive'
    $sddl = Get-ServiceSddl
    if ($sddl -like "*$sid*") {
        Set-ServiceSddl ($sddl -replace [regex]::Escape($aceForCaden), '')
        Say 'removed caden ACE from llama-server'
    } else {
        Say 'no caden ACE present; service ACL untouched'
    }
    Write-Output 'Reverted.'
    exit 0
}

# ------------------------------------------------------- precondition: ssh remote

Push-Location $Repo
try {
    $remote = (git remote get-url origin) -join ''
    $helper = (git config --get credential.helper) -join ''
} finally { Pop-Location }

if ($remote -notmatch '^(git@|ssh://)') {
    Write-Error @"
origin is still an HTTPS remote: $remote
credential.helper = $helper

Under S4U there is no DPAPI master key, so Git Credential Manager cannot hand
over the GitHub token and the push at the end of a transcription run would fail.
Move the repo to SSH first, with a key that GitHub accepts:

  gh auth refresh -h github.com -s admin:public_key
  gh ssh-key add ~/.ssh/id_ed25519.pub --title "slayden (transcription task)"
  git -C "$Repo" remote set-url origin git@github.com:Caden-Helbling/hsv-city-council-transcripts.git
  ssh -T git@github.com

Then run this script again.
"@
    exit 1
}
Say "origin is on SSH: $remote"

# ------------------------------------------------------------------ save for undo

$originalSddl = Get-ServiceSddl
$originalLogon = $task.Principal.LogonType
Say "saved rollback state (logon=$originalLogon)"

function Undo-Changes {
    Write-Warning 'Rolling back.'
    try {
        $p = New-ScheduledTaskPrincipal -UserId $Account -LogonType $originalLogon -RunLevel Limited
        Set-ScheduledTask -TaskName $TaskName -Principal $p | Out-Null
        Say "principal restored to $originalLogon"
    } catch { Write-Warning ("could not restore principal: " + $_.Exception.Message) }
    try {
        Set-ServiceSddl $originalSddl
        Say 'service ACL restored'
    } catch { Write-Warning ("could not restore service ACL: " + $_.Exception.Message) }
    try {
        Unregister-ScheduledTask -TaskName $ProbeName -Confirm:$false -ErrorAction SilentlyContinue
    } catch { }
}

# ------------------------------------------------------------------------- apply

try {
    # 1. service ACL: append an ACE for the caden account, before any SACL section
    $sddl = $originalSddl
    if ($sddl -like "*$sid*") {
        Say 'caden already has an ACE on llama-server; leaving the ACL alone'
    } else {
        if ($sddl -match '^(D:.*?)(S:.*)$') {
            $dacl = $matches[1]; $sacl = $matches[2]
        } else {
            $dacl = $sddl; $sacl = ''
        }
        Set-ServiceSddl ($dacl + $aceForCaden + $sacl)
        Say 'granted caden start/stop on llama-server'
    }

    # 2. principal -> S4U
    $p = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Limited
    Set-ScheduledTask -TaskName $TaskName -Principal $p | Out-Null
    Say 'principal -> S4U'

    # 3. verify under a real S4U token, not from this admin shell
    if (-not (Test-Path $ProbeDir)) { New-Item -ItemType Directory -Force $ProbeDir | Out-Null }
    $probeScript = Join-Path $ProbeDir 'probe.ps1'
    $probeResult = Join-Path $ProbeDir 'result.txt'
    if (Test-Path $probeResult) { Remove-Item $probeResult -Force }

    $body = @'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $dir 'result.txt'
$lines = @()
$sids = (whoami /groups /fo csv | ConvertFrom-Csv).SID
$lines += "interactive_sid_present=" + ($sids -contains 'S-1-5-4')
try {
    Stop-Service llama-server -Force
    $lines += "stop=OK"
    Start-Service llama-server
    Start-Service open-webui
    $lines += "start=OK"
} catch {
    $lines += "stop_or_start=FAIL " + $_.Exception.Message
}
try {
    Set-Location 'C:\Users\caden\code\hsv-city-council-transcripts'
    $r = cmd /c "git ls-remote origin HEAD 2>&1"
    if ($LASTEXITCODE -eq 0) { $lines += "git=OK" } else { $lines += "git=FAIL " + ($r -join ' ') }
} catch {
    $lines += "git=FAIL " + $_.Exception.Message
}
$lines | Set-Content -Path $out -Encoding utf8
'@
    Set-Content -Path $probeScript -Value $body -Encoding ascii

    Say 'running verification probe under the new S4U principal...'
    $act = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $probeScript + '"')
    $prin = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $ProbeName -Action $act -Principal $prin -Force | Out-Null
    Start-ScheduledTask -TaskName $ProbeName

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and -not (Test-Path $probeResult)) { Start-Sleep -Seconds 3 }
    Unregister-ScheduledTask -TaskName $ProbeName -Confirm:$false -ErrorAction SilentlyContinue

    if (-not (Test-Path $probeResult)) {
        throw 'probe produced no result within 120s - the S4U task did not run'
    }
    $res = Get-Content $probeResult
    $res | ForEach-Object { Say ('probe: ' + $_) }

    if ($res -join ' ' -match 'FAIL') {
        throw 'probe reported a failure under S4U (see lines above)'
    }
    if (-not ($res -match 'stop=OK') -or -not ($res -match 'git=OK')) {
        throw 'probe did not confirm both service control and git access'
    }
}
catch {
    Write-Warning ('FAILED: ' + $_.Exception.Message)
    Undo-Changes
    Write-Error 'Conversion rolled back; the task is unchanged.'
    exit 1
}

Write-Output ''
Write-Output "Done. '$TaskName' now runs whether or not caden is logged on."
Write-Output 'Verified under a real S4U token: llama-server stop/start and git access both work.'
Write-Output 'Undo with: -Revert'
