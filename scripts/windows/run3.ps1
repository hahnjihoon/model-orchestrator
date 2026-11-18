$ErrorActionPreference = 'Stop'
$projectDirectory = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $projectDirectory

$startupSettings = @{
    MODEL_NAME = 'qwen3-0.6b'
    VLLM_PORT = '8010'
    API_PORT = '8011'
    MODEL_START_TIMEOUT_SECONDS = '900'
}
if (Test-Path -LiteralPath '.env') {
    foreach ($settingLine in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        $settingLine = $settingLine.Trim()
        if (-not $settingLine -or $settingLine.StartsWith('#')) { continue }
        $settingPair = $settingLine -split '=', 2
        if ($settingPair.Count -eq 2) {
            $settingName = $settingPair[0].Trim()
            if ($settingName.StartsWith('QWEN_SMALL_')) {
                $settingName = $settingName.Substring(11)
            } elseif ($settingName -ne 'API_PORT') {
                continue
            }
            if ($startupSettings.ContainsKey($settingName)) {
                $startupSettings[$settingName] = $settingPair[1].Trim().Trim('"').Trim("'")
            }
        }
    }
}
$modelPort = [int]$startupSettings.VLLM_PORT
$apiPort = [int]$startupSettings.API_PORT
$startupTimeout = [int]$startupSettings.MODEL_START_TIMEOUT_SECONDS
if ($modelPort -lt 1 -or $modelPort -gt 65535 -or $apiPort -lt 1 -or $apiPort -gt 65535 -or $modelPort -eq $apiPort -or $startupTimeout -lt 1) {
    throw 'Invalid ports or model startup timeout in .env.'
}

& docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop before running this script.' }
& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration is invalid.' }

$runningProjectApi = @(& docker compose ps --status running --quiet api)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the project container.' }
$apiProbe = [System.Net.Sockets.TcpClient]::new()
try {
    $apiConnect = $apiProbe.ConnectAsync('127.0.0.1', $apiPort)
    if ($apiConnect.Wait(1000) -and $apiProbe.Connected -and $runningProjectApi.Count -eq 0) {
        throw "Port $apiPort is already in use outside this project's Docker API. Stop the old API first."
    }
} catch [System.AggregateException] {
} finally {
    $apiProbe.Dispose()
}

$wslHomeOutput = & wsl.exe -d Ubuntu-24.04 -- bash -lc 'echo ~'
if ($LASTEXITCODE -ne 0 -or -not $wslHomeOutput) { throw 'Could not read the Ubuntu home directory.' }
$wslHome = ($wslHomeOutput -join '').Trim()
$adapterPath = "$wslHome/aiq-train/output/eval-qlora"
$hasAdapterWeights = $false
& wsl.exe -d Ubuntu-24.04 -- test -f "$adapterPath/adapter_model.safetensors"
if ($LASTEXITCODE -eq 0) { $hasAdapterWeights = $true }
if (-not $hasAdapterWeights) {
    & wsl.exe -d Ubuntu-24.04 -- test -f "$adapterPath/adapter_model.bin"
    if ($LASTEXITCODE -eq 0) { $hasAdapterWeights = $true }
}
$launchMode = 'base'
if ($hasAdapterWeights) {
    & wsl.exe -d Ubuntu-24.04 -- test -f "$adapterPath/adapter_config.json"
    if ($LASTEXITCODE -ne 0) { throw "Adapter weights exist but adapter_config.json is missing: $adapterPath" }
    $startupSettings.MODEL_NAME = $startupSettings.MODEL_NAME + '-trained'
    $launchMode = 'trained'
    Write-Output "Using trained model weights: $adapterPath"
} else {
    Write-Output 'Using the original model. No trained adapter weights were found.'
}

$wslAddresses = & wsl.exe -d Ubuntu-24.04 -- hostname -I
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$modelAddresses = @(($wslAddresses -join ' ').Trim() -split '\s+' | Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' })
if ($modelAddresses.Count -eq 0) { throw 'Ubuntu IPv4 address was not found.' }
$modelAddress = $modelAddresses[0]
if (-not $modelAddress) { throw 'Ubuntu IPv4 address was not found.' }

$projectPath = $projectDirectory.Replace('\', '/')
if ($projectPath -notmatch '^[A-Za-z]:/') { throw 'The project must be on a local Windows drive.' }
$linuxPath = '/mnt/' + $projectPath.Substring(0, 1).ToLowerInvariant() + $projectPath.Substring(2)
$runtimeDirectory = Join-Path $projectDirectory 'runtime'
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$modelUrl = "http://${modelAddress}:${modelPort}/v1/models"
$modelLauncher = $null
$launchChecked = $false
$modelReady = $false
$deadline = [DateTime]::UtcNow.AddSeconds($startupTimeout)
Add-Type -AssemblyName System.Net.Http
$httpHandler = [System.Net.Http.HttpClientHandler]::new()
$httpHandler.UseProxy = $false
$httpClient = [System.Net.Http.HttpClient]::new($httpHandler)
$httpClient.Timeout = [TimeSpan]::FromSeconds(3)

try {
    while ([DateTime]::UtcNow -lt $deadline) {
        $unexpectedModel = $false
        $modelResponse = $null
        try {
            $modelResponse = $httpClient.GetAsync($modelUrl).GetAwaiter().GetResult()
            if ($modelResponse.IsSuccessStatusCode) {
                $modelPayload = $modelResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
                $modelReady = @($modelPayload.data | Where-Object { $_.id -eq $startupSettings.MODEL_NAME }).Count -gt 0
                $unexpectedModel = -not $modelReady
            }
        } catch {
        } finally {
            if ($null -ne $modelResponse) { $modelResponse.Dispose() }
        }
        if ($unexpectedModel) { throw "A different service or model is using $modelUrl." }
        if ($modelReady) { break }

        if (-not $launchChecked) {
            $launchChecked = $true
            $modelListening = $false
            $modelProbe = [System.Net.Sockets.TcpClient]::new()
            try {
                $modelConnect = $modelProbe.ConnectAsync($modelAddress, $modelPort)
                $modelListening = $modelConnect.Wait(1000) -and $modelProbe.Connected
            } catch {
            } finally {
                $modelProbe.Dispose()
            }
            if ($modelListening) {
                Write-Output "Waiting for the existing WSL model server: $modelUrl"
            } else {
                $loopbackModelReady = $false
                $loopbackResponse = $null
                try {
                    $loopbackResponse = $httpClient.GetAsync("http://127.0.0.1:${modelPort}/v1/models").GetAwaiter().GetResult()
                    if ($loopbackResponse.IsSuccessStatusCode) {
                        $loopbackPayload = $loopbackResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
                        $loopbackModelReady = @($loopbackPayload.data | Where-Object { $_.id -eq $startupSettings.MODEL_NAME }).Count -gt 0
                    }
                } catch {
                } finally {
                    if ($null -ne $loopbackResponse) { $loopbackResponse.Dispose() }
                }
                if ($loopbackModelReady) {
                    throw "The old model is reachable only through Windows localhost. Stop that model first, then rerun this script to bind it to the Ubuntu IP."
                }
                Write-Output "Starting the WSL model server on port $modelPort."
                $modelLauncher = Start-Process -FilePath 'wsl.exe' -WindowStyle Hidden -WorkingDirectory $projectDirectory -ArgumentList @('-d', 'Ubuntu-24.04', '--', 'bash', ('"' + $linuxPath + '/scripts/models/run3.sh"'), $launchMode) -RedirectStandardOutput (Join-Path $runtimeDirectory 'model3-launcher.log') -RedirectStandardError (Join-Path $runtimeDirectory 'model3-launcher-error.log') -PassThru
            }
        }
        if ($null -ne $modelLauncher -and $modelLauncher.HasExited) {
            throw 'The WSL model launcher exited. Check runtime/model3-launcher-error.log and runtime/vllm3.log.'
        }
        Start-Sleep -Seconds 2
    }
    if (-not $modelReady) { throw "Model readiness timed out after $startupTimeout seconds. Check runtime/vllm3.log." }
} finally {
    $httpClient.Dispose()
}

Write-Output ("Model ready: " + $modelUrl)
$previousModelName = [Environment]::GetEnvironmentVariable('MODEL_NAME', 'Process')
$previousModelPort = [Environment]::GetEnvironmentVariable('VLLM_PORT', 'Process')
try {
    $env:MODEL_NAME = $startupSettings.MODEL_NAME
    $env:VLLM_PORT = [string]$modelPort
    & docker compose up -d --build
    $apiStartupExitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable('MODEL_NAME', $previousModelName, 'Process')
    [Environment]::SetEnvironmentVariable('VLLM_PORT', $previousModelPort, 'Process')
}
if ($apiStartupExitCode -ne 0) { exit $apiStartupExitCode }
Write-Output ("Swagger: http://localhost:${apiPort}/docs")
exit 0
