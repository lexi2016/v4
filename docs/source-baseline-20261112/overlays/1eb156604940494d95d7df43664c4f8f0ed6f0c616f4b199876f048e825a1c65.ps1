[CmdletBinding()]
param(
    [string]$TaskXmlPath = '',
    [string]$ExpectedXmlSha256 = '5C7E3936EEAACA8B840E31B48D23EABB0F74A5132C74EDC115EFB84264245CE7',
    [string]$TaskPath = '\ReviewCore\',
    [string]$TaskName = 'ReviewCore_Pools_2115',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TaskXmlPath)) {
    $TaskXmlPath = Join-Path $PSScriptRoot 'ReviewCore_Pools_2115.xml'
}
if (-not (Test-Path -LiteralPath $TaskXmlPath -PathType Leaf)) {
    throw "Task XML not found: $TaskXmlPath"
}

$xmlPath = (Resolve-Path -LiteralPath $TaskXmlPath).Path
$xmlBytes = [System.IO.File]::ReadAllBytes($xmlPath)
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
$uriNode = $taskXml.SelectSingleNode('//t:RegistrationInfo/t:URI', $namespace)
$exec = $taskXml.SelectSingleNode('//t:Exec', $namespace)
if ($null -eq $uriNode -or $null -eq $exec) { throw 'Task XML is missing URI or Exec action' }
if ([string]$uriNode.InnerText -ne ($TaskPath + $TaskName)) { throw "Task URI mismatch: $($uriNode.InnerText)" }
if ([string]$exec.Command -ne 'C:\Python314\python.exe') { throw "Task action command mismatch: $($exec.Command)" }
$learningDirectory = Join-Path ([Environment]::GetFolderPath('Desktop')) (-join ([char]0x5B66, [char]0x4E60))
if ([string]$exec.WorkingDirectory -ne $learningDirectory) { throw "Task working directory mismatch: $($exec.WorkingDirectory)" }
$arguments = [string]$exec.Arguments
foreach ($required in @(
    '-X utf8 -m review_core.pool_pipeline',
    '--runtime-root',
    '--shared-root',
    '--calendar-path',
    '--close-root',
    '--bundle-root',
    '--shared-store-root'
)) {
    if ($arguments.IndexOf($required, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Task action arguments missing: $required"
    }
}

Write-Output "VALIDATED TaskPath=$TaskPath TaskName=$TaskName XmlSHA256=$actualXmlSha256"
if (-not $Apply) {
    Write-Output 'DRY_RUN: no Register-ScheduledTask call was made.'
    exit 0
}

Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Xml $registerXmlText -Force -ErrorAction Stop | Out-Null
Write-Output "APPLIED: registered $TaskPath$TaskName"
