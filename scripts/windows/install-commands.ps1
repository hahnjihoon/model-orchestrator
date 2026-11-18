$ErrorActionPreference = 'Stop'
$commandDirectory = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\bin'
$commandNames = @('run1', 'run2', 'run3', 'train')
foreach ($commandName in $commandNames) {
    $commandPath = Join-Path $commandDirectory ($commandName + '.cmd')
    if ((Test-Path -LiteralPath $commandPath) -and -not ([System.IO.File]::ReadAllText($commandPath, [System.Text.Encoding]::UTF8).Contains('rem model-orchestrator CLI'))) {
        throw "A different command already exists: $commandPath"
    }
}
New-Item -ItemType Directory -Path $commandDirectory -Force | Out-Null
foreach ($commandName in $commandNames) {
    $commandPath = Join-Path $commandDirectory ($commandName + '.cmd')
    $commandContent = @"
@echo off
rem model-orchestrator CLI
if not exist "%CD%\scripts\windows\$commandName.ps1" (
    echo Run $commandName from the model-orchestrator project root. 1>&2
    exit /b 1
)
call "%CD%\$commandName.cmd" %*
exit /b %errorlevel%
"@
    [System.IO.File]::WriteAllText($commandPath, $commandContent.Replace("`r`n", "`n").Replace("`n", "`r`n") + "`r`n", [System.Text.UTF8Encoding]::new($false))
}
$userPath = [string][Environment]::GetEnvironmentVariable('Path', 'User')
if (@($userPath -split ';' | Where-Object { $_.TrimEnd('\') -ieq $commandDirectory.TrimEnd('\') }).Count -eq 0) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $commandDirectory), 'User')
}
if (@($env:Path -split ';' | Where-Object { $_.TrimEnd('\') -ieq $commandDirectory.TrimEnd('\') }).Count -eq 0) {
    $env:Path = $env:Path.TrimEnd(';') + ';' + $commandDirectory
}
Write-Output 'Registered commands: run1, run2, run3, train. Use them from the project root.'
