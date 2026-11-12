[CmdletBinding()]
param(
    [string]$TaskXmlPath = '',
    [string]$ExpectedXmlSha256 = '76C5E1E5AB693FDEF7D3F81A478B6AB84B050B4F53CB8AE5B62581C447791E19',
    [string]$TaskPath = '\ReviewCore\',
    [string]$TaskName = 'ReviewCore_Video_Daily',
    [switch]$Apply,
    [switch]$DisableLegacyProducers
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TaskXmlPath)) {
    $TaskXmlPath = Join-Path $PSScriptRoot 'ReviewCore_Video_Daily.xml'
}

$LegacyTasks = @(
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2025_BilibiliFupan' },
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2030_FupanVideoCheck' },
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2040_FupanVideoASR' },
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2050_FupanStockdict' },
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2105_FupanVideoOcrAlign' },
    @{ TaskPath = '\'; TaskName = 'OpeningAdvisorV3_2108_FupanGapAndGuard' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2025_Nightly' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2030_VideoCheck' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2040_DownloadASR' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2050_Stockdict' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2105_OCRAlign' },
    @{ TaskPath = '\V3.5\'; TaskName = 'V35_CloseReview_2108_VideoGap' }
)

if (-not (Test-Path -LiteralPath $TaskXmlPath -PathType Leaf)) {
    throw "Task XML not found: $TaskXmlPath"
}

$xmlBytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $TaskXmlPath).Path)
$xmlHash = ([System.Security.Cryptography.SHA256]::Create()).ComputeHash($xmlBytes)
$actualXmlSha256 = ([System.BitConverter]::ToString($xmlHash) -replace '-', '').ToUpperInvariant()
if ($ExpectedXmlSha256 -and $actualXmlSha256 -ne $ExpectedXmlSha256.ToUpperInvariant()) {
    throw "Task XML SHA-256 mismatch: expected $ExpectedXmlSha256, got $actualXmlSha256"
}

$xmlText = [System.Text.Encoding]::UTF8.GetString($xmlBytes)
[xml]$taskXml = $xmlText
$registerXmlText = [System.Text.RegularExpressions.Regex]::Replace(
    $xmlText,
    '^(?:\uFEFF)?\s*<\?xml\b[^?]*\?>\s*',
    '',
    [System.Text.RegularExpressions.RegexOptions]::Singleline
)
if ([string]::IsNullOrWhiteSpace($registerXmlText) -or $registerXmlText -match '^\s*<\?xml\b') {
    throw 'Task XML could not be prepared for Register-ScheduledTask without an XML declaration'
}
$namespace = New-Object System.Xml.XmlNamespaceManager($taskXml.NameTable)
$namespace.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
$exec = $taskXml.SelectSingleNode('//t:Exec', $namespace)
if ($null -eq $exec) { throw 'Task XML is missing an Exec action' }
$command = [string]$exec.Command
$arguments = [string]$exec.Arguments
$workingDirectory = [string]$exec.WorkingDirectory
$learningDirectory = Join-Path ([Environment]::GetFolderPath('Desktop')) (-join ([char]0x5B66, [char]0x4E60))
$uri = [string]$taskXml.SelectSingleNode('//t:RegistrationInfo/t:URI', $namespace).InnerText
if ($uri -ne ($TaskPath + $TaskName)) { throw "Task URI mismatch: $uri" }
if ($command -ne 'C:\Python314\python.exe') { throw "Task action command mismatch: $command" }
if ($workingDirectory -ne $learningDirectory) { throw "Task working directory mismatch: $workingDirectory" }
foreach ($required in @(
    '-X utf8 -m review_core.scheduler_entry',
    '--data-root',
    '--mode acquire',
    '--allow-network',
    '--lookback-trading-days 5',
    '--funasr-path',
    '--ffmpeg-path',
    '--python-path C:\Python314\python.exe'
)) {
    if ($arguments.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Task action arguments missing: $required"
    }
}

Write-Output "VALIDATED TaskPath=$TaskPath TaskName=$TaskName XmlSHA256=$actualXmlSha256"
if (-not $Apply) {
    Write-Output 'DRY_RUN: no Register/Disable/Enable/Start-ScheduledTask call was made.'
    if ($DisableLegacyProducers) {
        Write-Output ("DRY_RUN: would disable exactly {0} legacy tasks after explicit -Apply." -f $LegacyTasks.Count)
    } else {
        Write-Output 'DRY_RUN: legacy producers remain unchanged (use -DisableLegacyProducers explicitly).'
    }
    exit 0
}

Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Xml $registerXmlText -Force -ErrorAction Stop | Out-Null
Write-Output "APPLIED: registered $TaskPath$TaskName"
if ($DisableLegacyProducers) {
    foreach ($legacy in $LegacyTasks) {
        Disable-ScheduledTask -TaskPath $legacy.TaskPath -TaskName $legacy.TaskName | Out-Null
        Write-Output "APPLIED: disabled $($legacy.TaskPath)$($legacy.TaskName)"
    }
}
