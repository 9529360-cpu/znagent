from __future__ import annotations

from pathlib import Path


PATH = Path('.github/workflows/zn-windows-clean-install.yml')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one old block, found {count}')
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding='utf-8')

    text = replace_once(
        text,
        '    runs-on: [self-hosted, Windows, X64, zn-interactive]\n',
        '    runs-on: windows-latest\n',
        'runner label',
    )

    text = replace_once(
        text,
        '''      - name: Require dedicated interactive Windows x64 runner
        run: |
          if ($env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ARCH -ne 'X64') {
            throw "Windows clean-install proof requires Windows X64; got $env:RUNNER_OS/$env:RUNNER_ARCH"
          }
          if ($env:RUNNER_NAME -ne 'zn-interactive') {
            throw "Windows clean-install proof requires the dedicated zn-interactive runner; got $env:RUNNER_NAME"
          }
          $sessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
          if ($sessionId -eq 0) {
            throw 'Windows clean-install proof requires a logged-on interactive session, not Session 0.'
          }
          git config core.longpaths true
          if ($LASTEXITCODE -ne 0) { throw "failed to enable Git long-path cleanup with exit code $LASTEXITCODE" }
          Write-Host "Windows clean-install runner: $env:RUNNER_NAME session=$sessionId"
''',
        '''      - name: Verify disposable GitHub-hosted Windows x64 runner
        run: |
          if ($env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ARCH -ne 'X64') {
            throw "Windows clean-install proof requires Windows X64; got $env:RUNNER_OS/$env:RUNNER_ARCH"
          }
          $sessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
          if ($sessionId -eq 0) {
            throw 'GitHub-hosted Windows clean-install proof requires a non-Session-0 user session.'
          }

          # This lane deliberately installs the production-identity artifact. Prove the disposable
          # hosted VM has no pre-existing ZN process, uninstall registration, or protocol identity
          # before dispatching the real installer so upgrade/uninstall state cannot contaminate the proof.
          $existingProcesses = @(Get-Process -Name 'ZN' -ErrorAction SilentlyContinue)
          if ($existingProcesses.Count -ne 0) {
            throw "Hosted clean-install runner already has $($existingProcesses.Count) ZN process(es); refusing to test against persistent host state."
          }
          $uninstallRoots = @(
            'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',
            'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',
            'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'
          )
          $existingInstalls = @(
            foreach ($root in $uninstallRoots) {
              Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
                Where-Object {
                  [string]$_.DisplayName -eq 'ZN' -or
                  [string]$_.DisplayIcon -like '*ZN.exe*'
                }
            }
          )
          if ($existingInstalls.Count -ne 0) {
            throw "Hosted clean-install runner already has $($existingInstalls.Count) ZN uninstall registration(s); refusing production-identity install."
          }
          if (Test-Path -LiteralPath 'HKCU:\\Software\\Classes\\zn') {
            throw 'Hosted clean-install runner already has a zn: protocol registration; refusing production-identity install.'
          }

          git config core.longpaths true
          if ($LASTEXITCODE -ne 0) { throw "failed to enable Git long-path cleanup with exit code $LASTEXITCODE" }
          Write-Host "Windows clean-install runner: $env:RUNNER_NAME session=$sessionId"
          Write-Host 'clean_install.preexisting_zn=false'
''',
        'runner precondition',
    )

    text = replace_once(
        text,
        '''          $process = Start-Process -FilePath $installer -ArgumentList '/S', "/D=$installDir" -PassThru
          $deadline = (Get-Date).AddMinutes(3)
          while (-not $process.HasExited -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
            $process.Refresh()
          }
          if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw 'ZN NSIS installer did not exit within 3 minutes'
          }
          if ($process.ExitCode -ne 0) { throw "ZN NSIS installer failed with exit code $($process.ExitCode)" }
''',
        '''          $process = Start-Process -FilePath $installer -ArgumentList '/S', "/D=$installDir" -PassThru
          $started = Get-Date
          $createTime = $process.StartTime.ToUniversalTime().ToString('o')
          Write-Host "clean_install.installer_pid=$($process.Id)"
          Write-Host "clean_install.installer_created=$createTime"
          $deadline = (Get-Date).AddMinutes(3)
          while (-not $process.HasExited -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
            $process.Refresh()
          }
          if (-not $process.HasExited) {
            Write-Host '--- installer process-tree evidence ---'
            $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
            $frontier = @($process.Id)
            $seen = [Collections.Generic.HashSet[int]]::new()
            while ($frontier.Count -gt 0) {
              $parent = [int]$frontier[0]
              if ($frontier.Count -eq 1) { $frontier = @() } else { $frontier = @($frontier[1..($frontier.Count - 1)]) }
              if (-not $seen.Add($parent)) { continue }
              $record = $all | Where-Object { [int]$_.ProcessId -eq $parent } | Select-Object -First 1
              if ($null -ne $record) {
                Write-Host ("pid={0} ppid={1} name={2}" -f $record.ProcessId, $record.ParentProcessId, $record.Name)
              }
              $children = @($all | Where-Object { [int]$_.ParentProcessId -eq $parent })
              foreach ($child in $children) { $frontier += [int]$child.ProcessId }
            }
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw 'ZN NSIS installer did not exit within 3 minutes on disposable hosted Windows'
          }
          $installSeconds = [int]((Get-Date) - $started).TotalSeconds
          Write-Host "clean_install.install_seconds=$installSeconds"
          Write-Host "clean_install.installer_exit_code=$($process.ExitCode)"
          if ($process.ExitCode -ne 0) { throw "ZN NSIS installer failed with exit code $($process.ExitCode)" }
''',
        'installer diagnostics',
    )

    text = replace_once(
        text,
        "          # Keep Electron's single-instance lock isolated from any live ZN in the interactive runner user session.\n",
        "          # Keep Electron's single-instance lock isolated from any accidental host state.\n",
        'single-instance comment',
    )

    checks = {
        'stale interactive runner label': '[self-hosted, Windows, X64, zn-interactive]' not in text,
        'stale static runner-name gate': "RUNNER_NAME -ne 'zn-interactive'" not in text,
        'hosted runner label': 'runs-on: windows-latest' in text,
        'host isolation proof': 'clean_install.preexisting_zn=false' in text,
        'installer hang diagnostics': 'installer process-tree evidence' in text,
    }
    missing = [label for label, ok in checks.items() if not ok]
    if missing:
        raise SystemExit('post-patch contract failed: ' + ', '.join(missing))

    PATH.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
