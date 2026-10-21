$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Get-FileIdentity([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{path=$Path; exists=$false}
    }
    $item = Get-Item -LiteralPath $Path
    $machine = $null
    if ($item.Extension -in @('.exe','.dll')) {
        $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            $reader = [IO.BinaryReader]::new($stream)
            if ($reader.ReadUInt16() -ne 0x5A4D) { throw 'Not an MZ executable' }
            $stream.Position = 0x3C
            $peOffset = $reader.ReadUInt32()
            if ($peOffset -gt 1048576 -or $peOffset + 6 -gt $stream.Length) { throw 'Invalid PE offset' }
            $stream.Position = $peOffset
            if ($reader.ReadUInt32() -ne 0x4550) { throw 'Not a PE executable' }
            $machine = ('0x{0:X4}' -f $reader.ReadUInt16())
        } finally { $stream.Dispose() }
    }
    return [ordered]@{path=$Path; exists=$true; length=$item.Length;
        mtime_utc=$item.LastWriteTimeUtc.ToString('o');
        sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();
        machine=$machine; file_version=$item.VersionInfo.FileVersion;
        product_version=$item.VersionInfo.ProductVersion}
}

$fixedPaths = @(
    'C:\new_tdx_mock\PYPlugins\user\tqcenter.py',
    'C:\new_tdx_mock\PYPlugins\sys\tqcenter.py',
    'C:\new_tdx_mock\PYPlugins\TPythClient.dll',
    'C:\new_tdx_mock\TdxW.exe',
    'C:\new_tdx_mock\T0002\blocknew\KSB.blk',
    'C:\new_tdx_mock\T0002\blocknew\KSB.dat',
    'C:\new_tdx_mock\T0002\fastxginfo.dat'
)
$before = @(foreach ($path in $fixedPaths) { Get-FileIdentity $path })
$commands = @(Get-Command -Name python,python3,py -All -ErrorAction SilentlyContinue |
    Select-Object Name,CommandType,Source,Path)
$runtimePaths = @($commands | Where-Object { $_.CommandType -eq 'Application' } |
    ForEach-Object { $_.Path })
$pythonRegistry = @()
foreach ($root in @('HKCU:\Software\Python\PythonCore',
                   'HKLM:\Software\Python\PythonCore',
                   'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
    if (Test-Path -LiteralPath $root) {
        $versions = @(Get-ChildItem -LiteralPath $root)
        if ($versions.Count -gt 20) { throw 'Python registry enumeration exceeds bound' }
        foreach ($version in $versions) {
            $installKey = $version.OpenSubKey('InstallPath')
            if ($null -ne $installKey) {
                try {
                    $installPath = [string]$installKey.GetValue('')
                    $exePath = [string]$installKey.GetValue('ExecutablePath')
                    if (-not $exePath -and $installPath) { $exePath = Join-Path $installPath 'python.exe' }
                    $pythonRegistry += [ordered]@{key=$version.Name; install_path=$installPath; executable_path=$exePath}
                    if ($exePath) { $runtimePaths += $exePath }
                } finally { $installKey.Close() }
            }
        }
    }
}
$runtimes = @(foreach ($path in @($runtimePaths | Sort-Object -Unique)) {
    # WindowsApps app execution aliases are links, not installed Python evidence.
    if ($path -match '\\WindowsApps\\') {
        [ordered]@{path=$path; excluded='APP_EXECUTION_ALIAS_NOT_INVOKED'}
    } else { Get-FileIdentity $path }
})
$pluginInventory = @(foreach ($dir in @('C:\new_tdx_mock\PYPlugins',
        'C:\new_tdx_mock\PYPlugins\sys','C:\new_tdx_mock\PYPlugins\user')) {
    if (Test-Path -LiteralPath $dir -PathType Container) {
        $items = @(Get-ChildItem -LiteralPath $dir -Force)
        if ($items.Count -gt 150) { throw 'Plugin directory exceeds inventory bound' }
        [ordered]@{path=$dir; items=@($items | Select-Object Name,Length,PSIsContainer)}
    }
})
$processes = @(Get-Process -Name TdxW -ErrorAction SilentlyContinue |
    Select-Object Id,Path,@{Name='start_time_utc'; Expression={$_.StartTime.ToUniversalTime().ToString('o')}})
$after = @(foreach ($path in $fixedPaths) { Get-FileIdentity $path })
[ordered]@{record_kind='METADATA_ONLY_NO_SDK_OR_RUNTIME_EXECUTION';
    acquired_at_utc=[DateTime]::UtcNow.ToString('o'); before=$before; after=$after;
    commands=$commands; python_registry=$pythonRegistry; runtimes=$runtimes;
    plugin_inventory=$pluginInventory; tdx_processes=$processes;
    sdk_import_count=0; init_connect_count=0; formula_call_count=0;
    research_only=$true; production_allowed=$false; buy_gate_updated=$false; orders_sent=$false
} | ConvertTo-Json -Depth 9 -Compress
