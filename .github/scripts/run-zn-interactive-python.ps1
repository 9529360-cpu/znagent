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
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class ZNInteractivePythonLauncherNative {
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint INFINITE = 0xFFFFFFFF;
    private const uint WAIT_OBJECT_0 = 0x00000000;
    private const uint WAIT_FAILED = 0xFFFFFFFF;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

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

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AllowSetForegroundWindow(uint processId);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessW(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr threadHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr processHandle, out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(IntPtr processHandle, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    private static string QuoteArgument(string value) {
        if (value == null) {
            value = string.Empty;
        }
        if (value.Length > 0 && value.IndexOfAny(new char[] { ' ', '\t', '\n', '\v', '"' }) < 0) {
            return value;
        }

        StringBuilder quoted = new StringBuilder();
        quoted.Append('"');
        int backslashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') {
                backslashes++;
                continue;
            }
            if (ch == '"') {
                quoted.Append('\\', (backslashes * 2) + 1);
                quoted.Append('"');
                backslashes = 0;
                continue;
            }
            if (backslashes > 0) {
                quoted.Append('\\', backslashes);
                backslashes = 0;
            }
            quoted.Append(ch);
        }
        if (backslashes > 0) {
            quoted.Append('\\', backslashes * 2);
        }
        quoted.Append('"');
        return quoted.ToString();
    }

    private static StringBuilder BuildCommandLine(string executable, string[] args) {
        StringBuilder commandLine = new StringBuilder();
        commandLine.Append(QuoteArgument(executable));
        if (args != null) {
            foreach (string arg in args) {
                commandLine.Append(' ');
                commandLine.Append(QuoteArgument(arg));
            }
        }
        return commandLine;
    }

    public static int RunForegroundAuthorized(
        string executable,
        string[] args,
        IntPtr expectedForegroundHwnd
    ) {
        if (GetForegroundWindow() != expectedForegroundHwnd) {
            throw new InvalidOperationException(
                "Interactive launcher lost exact foreground before child creation."
            );
        }

        STARTUPINFO startupInfo = new STARTUPINFO();
        startupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        PROCESS_INFORMATION processInformation;
        StringBuilder commandLine = BuildCommandLine(executable, args);

        if (!CreateProcessW(
            executable,
            commandLine,
            IntPtr.Zero,
            IntPtr.Zero,
            false,
            CREATE_SUSPENDED,
            IntPtr.Zero,
            null,
            ref startupInfo,
            out processInformation
        )) {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "CreateProcessW(CREATE_SUSPENDED) failed for interactive Python child."
            );
        }

        bool resumed = false;
        try {
            if (GetForegroundWindow() != expectedForegroundHwnd) {
                throw new InvalidOperationException(
                    "Interactive launcher lost exact foreground before foreground eligibility transfer."
                );
            }
            if (!AllowSetForegroundWindow(processInformation.dwProcessId)) {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "AllowSetForegroundWindow failed for exact interactive Python child."
                );
            }

            uint resumeResult = ResumeThread(processInformation.hThread);
            if (resumeResult == UInt32.MaxValue) {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "ResumeThread failed for foreground-authorized interactive Python child."
                );
            }
            resumed = true;

            uint waitResult = WaitForSingleObject(processInformation.hProcess, INFINITE);
            if (waitResult == WAIT_FAILED) {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "WaitForSingleObject failed for interactive Python child."
                );
            }
            if (waitResult != WAIT_OBJECT_0) {
                throw new InvalidOperationException(
                    "Unexpected wait result for interactive Python child: " + waitResult
                );
            }

            uint exitCode;
            if (!GetExitCodeProcess(processInformation.hProcess, out exitCode)) {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "GetExitCodeProcess failed for interactive Python child."
                );
            }
            return unchecked((int)exitCode);
        } catch {
            if (!resumed || WaitForSingleObject(processInformation.hProcess, 0) != WAIT_OBJECT_0) {
                TerminateProcess(processInformation.hProcess, 1);
            }
            throw;
        } finally {
            if (processInformation.hThread != IntPtr.Zero) {
                CloseHandle(processInformation.hThread);
            }
            if (processInformation.hProcess != IntPtr.Zero) {
                CloseHandle(processInformation.hProcess);
            }
        }
    }
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

    # Windows foreground eligibility is deliberately transferred to only this exact
    # Python PID while it is suspended. This removes the race where the child could
    # start running before AllowSetForegroundWindow and avoids ASFW_ANY. Product E2E
    # fixtures remain unchanged and still have to prove their normal exact foreground
    # and result postconditions.
    $exitCode = [ZNInteractivePythonLauncherNative]::RunForegroundAuthorized(
        $Python,
        $CommandArgs,
        $form.Handle
    )
} finally {
    $form.Close()
    $form.Dispose()
}

exit $exitCode