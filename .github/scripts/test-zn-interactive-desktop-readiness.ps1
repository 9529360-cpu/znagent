param(
    [string]$ExpectedRunnerName = 'zn-interactive'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "Interactive desktop readiness requires Windows; got $env:RUNNER_OS"
}
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne $ExpectedRunnerName) {
    throw "Interactive desktop readiness expected runner '$ExpectedRunnerName'; got '$env:RUNNER_NAME'."
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ZNInteractiveDesktopNative {
    [DllImport("kernel32.dll")]
    public static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool ProcessIdToSessionId(uint processId, out uint sessionId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint desiredAccess);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SwitchDesktop(IntPtr desktop);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseDesktop(IntPtr desktop);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetForegroundWindow(IntPtr hwnd);
}
'@

function Get-ProcessSessionId {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    [uint32]$sessionId = 0
    if (-not [ZNInteractiveDesktopNative]::ProcessIdToSessionId([uint32]$ProcessId, [ref]$sessionId)) {
        throw "ProcessIdToSessionId($ProcessId) failed with Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    return [int]$sessionId
}

$currentProcess = Get-Process -Id $PID -ErrorAction Stop
$currentSessionId = [int]$currentProcess.SessionId
$activeConsoleSessionId = [int][ZNInteractiveDesktopNative]::WTSGetActiveConsoleSessionId()
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host "interactive_readiness.runner=$($env:RUNNER_NAME)"
Write-Host "interactive_readiness.identity=$currentIdentity"
Write-Host "interactive_readiness.process_id=$PID"
Write-Host "interactive_readiness.process_session_id=$currentSessionId"
Write-Host "interactive_readiness.active_console_session_id=$activeConsoleSessionId"

if ($currentSessionId -eq 0) {
    throw 'Interactive runner is executing in Session 0; real desktop E2E requires a logged-on user session.'
}
if ($activeConsoleSessionId -eq [uint32]::MaxValue) {
    throw 'Windows reports no active console session.'
}
if ($currentSessionId -ne $activeConsoleSessionId) {
    throw "Interactive runner session $currentSessionId is not the active console session $activeConsoleSessionId. The host is likely disconnected, switched to another session, or otherwise not attached to the current input desktop."
}

$DESKTOP_READOBJECTS = 0x0001
$DESKTOP_SWITCHDESKTOP = 0x0100
$DESKTOP_WRITEOBJECTS = 0x0080
$desktop = [ZNInteractiveDesktopNative]::OpenInputDesktop(
    0,
    $false,
    $DESKTOP_READOBJECTS -bor $DESKTOP_WRITEOBJECTS -bor $DESKTOP_SWITCHDESKTOP
)
if ($desktop -eq [IntPtr]::Zero) {
    throw "Interactive runner cannot open the Windows input desktop; Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()). The user session may be locked or disconnected."
}
try {
    if (-not [ZNInteractiveDesktopNative]::SwitchDesktop($desktop)) {
        throw "Interactive runner cannot switch to the Windows input desktop; Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()). The desktop may be locked or non-interactive."
    }
} finally {
    [void][ZNInteractiveDesktopNative]::CloseDesktop($desktop)
}

$originalForeground = [ZNInteractiveDesktopNative]::GetForegroundWindow()
if ($originalForeground -eq [IntPtr]::Zero) {
    throw 'Windows input desktop has no foreground window. The interactive session is not ready for foreground/focus acceptance.'
}
[uint32]$foregroundPid = 0
[void][ZNInteractiveDesktopNative]::GetWindowThreadProcessId($originalForeground, [ref]$foregroundPid)
$foregroundSessionId = Get-ProcessSessionId -ProcessId ([int]$foregroundPid)
$foregroundName = '<unavailable>'
try {
    $foregroundName = (Get-Process -Id ([int]$foregroundPid) -ErrorAction Stop).ProcessName
} catch {}
Write-Host "interactive_readiness.foreground_hwnd=$([int64]$originalForeground)"
Write-Host "interactive_readiness.foreground_pid=$foregroundPid"
Write-Host "interactive_readiness.foreground_process=$foregroundName"
Write-Host "interactive_readiness.foreground_session_id=$foregroundSessionId"

if ($foregroundSessionId -ne $currentSessionId) {
    throw "Foreground window belongs to session $foregroundSessionId, but runner executes in session $currentSessionId."
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "ZN Interactive Readiness $([Guid]::NewGuid().ToString('N'))"
$form.Width = 320
$form.Height = 120
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.Left = 32
$form.Top = 32
$form.ShowInTaskbar = $true
$probeForeground = $false
$setForegroundAccepted = $false
try {
    $form.Show()
    $form.Activate()
    $setForegroundAccepted = [ZNInteractiveDesktopNative]::SetForegroundWindow($form.Handle)
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    do {
        [System.Windows.Forms.Application]::DoEvents()
        if ([ZNInteractiveDesktopNative]::GetForegroundWindow() -eq $form.Handle) {
            $probeForeground = $true
            break
        }
        Start-Sleep -Milliseconds 50
    } while ([DateTime]::UtcNow -lt $deadline)
} finally {
    $form.Close()
    $form.Dispose()
    if ($originalForeground -ne [IntPtr]::Zero) {
        [void][ZNInteractiveDesktopNative]::SetForegroundWindow($originalForeground)
    }
}

Write-Host "interactive_readiness.probe_set_foreground_returned=$setForegroundAccepted"
Write-Host "interactive_readiness.probe_became_foreground=$probeForeground"
if (-not $probeForeground) {
    throw "Runner session can access the input desktop but cannot make an owned desktop window foreground (SetForegroundWindow returned $setForegroundAccepted). Windows foreground entitlement is not currently usable for real GUI acceptance."
}

Write-Host 'interactive_readiness.ready=true'
