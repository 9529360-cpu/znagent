param(
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "Interactive Python launcher requires Windows; got $env:RUNNER_OS"
}
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne 'zn-interactive') {
    throw "Interactive Python launcher requires zn-interactive; got $env:RUNNER_NAME"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Interactive Python executable does not exist: $Python"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ZNInteractivePythonLauncherNative {
    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool BringWindowToTop(IntPtr hwnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetForegroundWindow(IntPtr hwnd);
}
'@

function Wait-ExactForeground {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$Hwnd,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    do {
        [System.Windows.Forms.Application]::DoEvents()
        if ([ZNInteractivePythonLauncherNative]::GetForegroundWindow() -eq $Hwnd) {
            return $true
        }
        Start-Sleep -Milliseconds 20
    } while ([DateTime]::UtcNow -lt $deadline)
    return [ZNInteractivePythonLauncherNative]::GetForegroundWindow() -eq $Hwnd
}

function Acquire-ExactForeground {
    param([Parameter(Mandatory = $true)][IntPtr]$TargetHwnd)

    if ([ZNInteractivePythonLauncherNative]::GetForegroundWindow() -eq $TargetHwnd) {
        return 'already-foreground'
    }

    [void][ZNInteractivePythonLauncherNative]::BringWindowToTop($TargetHwnd)
    [void][ZNInteractivePythonLauncherNative]::SetForegroundWindow($TargetHwnd)
    if (Wait-ExactForeground -Hwnd $TargetHwnd -TimeoutMilliseconds 350) {
        return 'direct'
    }

    $foreground = [ZNInteractivePythonLauncherNative]::GetForegroundWindow()
    if ($foreground -eq [IntPtr]::Zero) {
        return $null
    }
    [uint32]$foregroundPid = 0
    [uint32]$foregroundThreadId = [ZNInteractivePythonLauncherNative]::GetWindowThreadProcessId(
        $foreground,
        [ref]$foregroundPid
    )
    [uint32]$currentThreadId = [ZNInteractivePythonLauncherNative]::GetCurrentThreadId()
    if ($foregroundThreadId -eq 0 -or $foregroundThreadId -eq $currentThreadId) {
        return $null
    }

    if (-not [ZNInteractivePythonLauncherNative]::AttachThreadInput(
        $currentThreadId,
        $foregroundThreadId,
        $true
    )) {
        Write-Host "interactive_launcher.attach_thread_input_error=$([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
        return $null
    }
    try {
        [void][ZNInteractivePythonLauncherNative]::BringWindowToTop($TargetHwnd)
        [void][ZNInteractivePythonLauncherNative]::SetForegroundWindow($TargetHwnd)
        if (Wait-ExactForeground -Hwnd $TargetHwnd -TimeoutMilliseconds 2000) {
            return 'shared-input-bootstrap'
        }
        return $null
    } finally {
        [void][ZNInteractivePythonLauncherNative]::AttachThreadInput(
            $currentThreadId,
            $foregroundThreadId,
            $false
        )
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "ZN Interactive E2E Launcher $([Guid]::NewGuid().ToString('N'))"
$form.Width = 240
$form.Height = 80
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.Left = 8
$form.Top = 8
$form.ShowInTaskbar = $false
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedToolWindow

$exitCode = 1
try {
    $form.Show()
    $form.Activate()
    $mode = Acquire-ExactForeground -TargetHwnd $form.Handle
    if ([string]::IsNullOrWhiteSpace([string]$mode)) {
        throw 'Interactive launcher could not establish its exact foreground precondition.'
    }
    Write-Host "interactive_launcher.foreground_mode=$mode"
    Write-Host "interactive_launcher.python=$([IO.Path]::GetFileName($Python))"

    # Keep this exact foreground parent alive while it starts the test process. Windows
    # explicitly allows a process started by the foreground process to request foreground.
    & $Python @CommandArgs
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 1
    }
} finally {
    $form.Close()
    $form.Dispose()
}

exit $exitCode
