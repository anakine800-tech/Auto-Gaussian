param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedPath,
    [string]$OutputPath,
    [int]$TimeoutSeconds = 15
)

function Write-ProbeResult {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Payload,
        [int]$ExitCode
    )
    $json = $Payload | ConvertTo-Json -Compress -Depth 4
    if ($OutputPath) {
        [System.IO.File]::WriteAllText($OutputPath, $json, [System.Text.UTF8Encoding]::new($false))
    } else {
        Write-Output $json
    }
    exit $ExitCode
}

$typeDefinition = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public sealed class CodexWindowInfo {
    public long Handle;
    public int ProcessId;
    public string Text;
    public string ClassName;
    public bool Visible;
}

public static class CodexWindowProbe {
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr extraData);
    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr extraData);
    [DllImport("user32.dll")]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")]
    private static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    private static CodexWindowInfo Read(IntPtr handle) {
        uint processId;
        GetWindowThreadProcessId(handle, out processId);
        var text = new StringBuilder(Math.Max(1024, GetWindowTextLength(handle) + 1));
        GetWindowText(handle, text, text.Capacity);
        var className = new StringBuilder(256);
        GetClassName(handle, className, className.Capacity);
        return new CodexWindowInfo {
            Handle = handle.ToInt64(),
            ProcessId = (int)processId,
            Text = text.ToString(),
            ClassName = className.ToString(),
            Visible = IsWindowVisible(handle)
        };
    }

    public static List<CodexWindowInfo> All() {
        var result = new List<CodexWindowInfo>();
        EnumWindows(delegate(IntPtr top, IntPtr ignored) {
            result.Add(Read(top));
            EnumChildWindows(top, delegate(IntPtr child, IntPtr childIgnored) {
                result.Add(Read(child));
                return true;
            }, IntPtr.Zero);
            return true;
        }, IntPtr.Zero);
        return result;
    }
}
"@

Add-Type -TypeDefinition $typeDefinition -Language CSharp
$expectedFile = [System.IO.Path]::GetFileName($ExpectedPath)
$expectedProject = [System.IO.Path]::GetFileName([System.IO.Path]::GetDirectoryName($ExpectedPath))
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

do {
    $gviewPids = @(Get-Process -Name gview -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $windows = @(
        [CodexWindowProbe]::All() |
            Where-Object { $gviewPids -contains $_.ProcessId -and $_.Visible -and $_.Text }
    )
    $texts = @($windows | ForEach-Object { $_.Text })
    $errors = @(
        $texts | Where-Object {
            $_ -match 'Unknown file type' -or
            $_ -match 'CFileAction::LoadFile' -or
            $_ -match '^Error$'
        }
    )
    if ($errors.Count -gt 0) {
        Write-ProbeResult -Payload ([ordered]@{
            loaded = $false
            reason = 'gaussview_error_dialog'
            expected_path = $ExpectedPath
            errors = $errors
            visible_text = $texts
        }) -ExitCode 52
    }

    $combined = $texts -join "`n"
    $hasFile = $combined.IndexOf($expectedFile, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    $hasProject = $combined.IndexOf($expectedProject, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    if ($hasFile -and $hasProject) {
        Write-ProbeResult -Payload ([ordered]@{
            loaded = $true
            reason = 'document_window_confirmed'
            expected_path = $ExpectedPath
            matching_file = $expectedFile
            matching_project = $expectedProject
            errors = @()
            visible_text = $texts
        }) -ExitCode 0
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

Write-ProbeResult -Payload ([ordered]@{
    loaded = $false
    reason = 'document_window_not_confirmed_before_timeout'
    expected_path = $ExpectedPath
    errors = @()
    visible_text = $texts
}) -ExitCode 53
