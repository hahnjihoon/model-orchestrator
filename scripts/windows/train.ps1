param(
    [string]$Data = 'train.jsonl',
    [string]$OutputDirectory = '~/aiq-train/output/eval-qlora',
    [int]$Epochs = 1,
    [int]$MaxLength = 2048,
    [string]$ResumeFromCheckpoint = '',
    [switch]$CheckData
)

$ErrorActionPreference = 'Stop'
$projectDirectory = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $projectDirectory
if ($Epochs -lt 1 -or $MaxLength -lt 32) {
    throw 'Epochs must be at least 1 and MaxLength must be at least 32.'
}
$projectPath = $projectDirectory.Replace('\', '/')
if ($projectPath -notmatch '^[A-Za-z]:/') {
    throw 'The project must be on a local Windows drive.'
}
$linuxProjectPath = '/mnt/' + $projectPath.Substring(0, 1).ToLowerInvariant() + $projectPath.Substring(2)
if (-not $OutputDirectory) {
    $OutputDirectory = '~/aiq-train/output/eval-qlora'
}
if ([System.IO.Path]::IsPathRooted($Data)) {
    $dataPath = [System.IO.Path]::GetFullPath($Data).Replace('\', '/')
} else {
    $dataPath = [System.IO.Path]::GetFullPath((Join-Path $projectDirectory $Data)).Replace('\', '/')
}
if ($dataPath -notmatch '^[A-Za-z]:/') {
    throw 'The data file must be on a local Windows drive.'
}
if (-not (Test-Path -LiteralPath $dataPath -PathType Leaf)) {
    throw "Training data was not found: $dataPath"
}
$linuxDataPath = '/mnt/' + $dataPath.Substring(0, 1).ToLowerInvariant() + $dataPath.Substring(2)
$wslHomeOutput = & wsl.exe -d Ubuntu-24.04 -- bash -lc 'echo ~'
if ($LASTEXITCODE -ne 0 -or -not $wslHomeOutput) {
    throw 'Could not read the Ubuntu home directory.'
}
$wslHome = ($wslHomeOutput -join '').Trim()
$trainingArguments = @(
    '-d', 'Ubuntu-24.04', '--', "$wslHome/aiq-train/.venv/bin/python", '-u',
    "$linuxProjectPath/train.py", '--data', $linuxDataPath,
    '--output-dir', $OutputDirectory, '--epochs', [string]$Epochs,
    '--max-length', [string]$MaxLength
)
if ($ResumeFromCheckpoint) {
    $trainingArguments += @('--resume-from-checkpoint', $ResumeFromCheckpoint)
}
if ($CheckData) {
    $trainingArguments += '--check-data'
}
& wsl.exe @trainingArguments
exit $LASTEXITCODE
