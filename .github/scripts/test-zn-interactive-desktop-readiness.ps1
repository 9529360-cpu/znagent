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

    [DllImport("wtsapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool WTSQuerySessionInformationW(
        IntPtr server,
        uint sessionId,
        int infoClass,
        out IntPtr buffer,
        out uint bytesReturned
    );

    [DllImport("wtsapi32.dll")]
    public static extern void WTSFreeMemory(IntPtr memory);

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

function Get-WtsConnectState {
    param([Parameter(Mandatory = $true)][uint32]$SessionId)

    # WTS_INFO_CLASS.WTSConnectState == 8. WTS_CONNECTSTATE_CLASS.WTSActive == 0.
    $WTS_CONNECT_STATE = 8
    [IntPtr]$buffer = [IntPtr]::Zero
    [uint32]$bytesReturned = 0
    if (-not [ZNInteractiveDesktopNative]::WTSQuerySessionInformationW(
        [IntPtr]::Zero,
        $SessionId,
        $WTS_CONNECT_STATE,
        [ref]$buffer,
        [ref]$bytesReturned
    )) {
        throw "WTSQuerySessionInformation(WTSConnectState) for session $SessionId failed with Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    try {
        if ($buffer -eq [IntPtr]::Zero -or $bytesReturned -lt 4) {
            throw "WTSConnectState returned an invalid buffer for session $SessionId"
        }
        return [Runtime.InteropServices.Marshal]::ReadInt32($buffer)
    } finally {
        if ($buffer -ne [IntPtr]::Zero) {
            [ZNInteractiveDesktopNative]::WTSFreeMemory($buffer)
        }
    }
}

function Get-WtsConnectStateName {
    param([Parameter(Mandatory = $true)][int]$State)
    $names = @(
        'WTSActive',
        'WTSConnected',
        'WTSConnectQuery',
        'WTSShadow',
        'WTSDisconnected',
        'WTSIdle',
        'WTSListen',
        'WTSReset',
        'WTSDown',
        'WTSInit'
    )
    if ($State -ge 0 -and $State -lt $names.Count) {
        return $names[$State]
    }
    return "Unknown($State)"
}

$currentProcess = Get-Process -Id $PID -ErrorAction Stop
$currentSessionId = [int]$currentProcess.SessionId
[uint32]$activeConsoleSessionId = [ZNInteractiveDesktopNative]::WTSGetActiveConsoleSessionId()
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host "interactive_readiness.runner=$($env:RUNNER_NAME)"
Write-Host "interactive_readiness.identity=$currentIdentity"
Write-Host "interactive_readiness.process_id=$PID"
Write-Host "interactive_readiness.process_session_id=$currentSessionId"
if ($activeConsoleSessionId -eq [uint32]::MaxValue) {
    Write-Host 'interactive_readiness.active_console_session_id=none'
} else {
    Write-Host "interactive_readiness.active_console_session_id=$activeConsoleSessionId"
}

if ($currentSessionId -eq 0) {
    throw 'Interactive runner is executing in Session 0; real desktop E2E requires a logged-on user session.'
}

$currentWtsState = Get-WtsConnectState -SessionId ([uint32]$currentSessionId)
$currentWtsStateName = Get-WtsConnectStateName -State $currentWtsState
Write-Host "interactive_readiness.wts_connect_state=$currentWtsStateName"
if ($currentWtsState -ne 0) {
    throw "Interactive runner session $currentSessionId is not WTSActive; current state is $currentWtsStateName. Real GUI acceptance requires a user who is logged on and actively connected to the device."
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
    throw "Interactive runner cannot open the Windows input desktop; Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()). The user session may be locked, disconnected, or on a non-input desktop."
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
if ($foregroundPid -eq 0) {
    throw 'GetForegroundWindow returned a window without an owning process id.'
}
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
    throw "Runner session is WTSActive and can access the input desktop, but it cannot make an owned desktop window foreground (SetForegroundWindow returned $setForegroundAccepted). Windows foreground entitlement is not currently usable for real GUI acceptance."
}

Write-Host 'interactive_readiness.ready=true'
