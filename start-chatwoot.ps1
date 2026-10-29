# start-chatwoot.ps1 - One-command Chatwoot restart after a machine reboot.
# 1. Starts Docker Desktop if it isn't running.
# 2. Starts (or ensures) the ngrok tunnel to localhost:3000.
# 3. Syncs FRONTEND_URL in .env with the live ngrok URL.
# 4. Brings up the Chatwoot compose stack and waits until Rails is healthy.
# 5. Verifies the Telegram bot webhook; re-registers it if it points at a stale URL.

[CmdletBinding()]
param(
    [string]$Root = 'C:\Users\robel\Downloads\chatwoot',
    [int]$RailsTimeoutSec = 180
)

$ComposeFile = Join-Path $Root 'docker-compose.production.yaml'
$EnvFile = Join-Path $Root '.env'

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Docker daemon -----------------------------------------------------------
Step 'Checking Docker...'
$dockerReady = $false
try {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    $dockerReady = ($LASTEXITCODE -eq 0)
} catch { $dockerReady = $false }

if (-not $dockerReady) {
    Step 'Docker is not running - starting Docker Desktop'
    $desktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $desktop)) { Fail "Docker Desktop not found at $desktop. Start Docker manually and re-run." }
    Start-Process $desktop
    $deadline = (Get-Date).AddSeconds(150)
    while (-not $dockerReady -and (Get-Date) -lt $deadline) {
        Start-Sleep 5
        try {
            docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
            $dockerReady = ($LASTEXITCODE -eq 0)
        } catch { $dockerReady = $false }
    }
    if (-not $dockerReady) { Fail 'Docker did not become ready in time.' }
}
Step 'Docker is ready'

# 2. ngrok tunnel ------------------------------------------------------------
Step 'Checking ngrok tunnel...'
function Get-NgrokUrl {
    try {
        $tunnels = (Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3).tunnels
        return ($tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1).public_url
    } catch { return $null }
}

$publicUrl = Get-NgrokUrl
if (-not $publicUrl) {
    $ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($ngrok) {
        Step 'ngrok not running - starting "ngrok http 3000" in the background'
        Start-Process -FilePath $ngrok.Source -ArgumentList 'http', '3000' -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(30)
        while (-not $publicUrl -and (Get-Date) -lt $deadline) {
            Start-Sleep 3
            $publicUrl = Get-NgrokUrl
        }
    }
}
if ($publicUrl) {
    Step "ngrok public URL: $publicUrl"
} else {
    Write-Host 'WARNING: no ngrok tunnel available - Chatwoot will still start, but external webhooks (Telegram) will not work.' -ForegroundColor Yellow
}

# 3. Sync FRONTEND_URL in .env -----------------------------------------------
$envText = Get-Content $EnvFile -Raw
$match = [regex]::Match($envText, '(?m)^FRONTEND_URL=(.*)$')
$currentEnvUrl = if ($match.Success) { $match.Groups[1].Value.Trim() } else { '' }

if ($publicUrl -and $publicUrl -ne $currentEnvUrl) {
    Step "FRONTEND_URL changed: $currentEnvUrl -> $publicUrl (updating .env)"
    $newText = [regex]::Replace($envText, '(?m)^FRONTEND_URL=.*$', "FRONTEND_URL=$publicUrl")
    Set-Content -Path $EnvFile -Value $newText -NoNewline
} else {
    Step "FRONTEND_URL unchanged ($currentEnvUrl)"
}

# 4. Start the stack and wait for Rails ---------------------------------------
Step 'Starting Chatwoot stack (docker compose up -d)...'
docker compose -p chatwoot --project-directory $Root -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) { Fail 'docker compose up failed.' }

Step "Waiting for Rails at http://localhost:3000 (up to $RailsTimeoutSec s)..."
$deadline = (Get-Date).AddSeconds($RailsTimeoutSec)
$version = $null
while (-not $version -and (Get-Date) -lt $deadline) {
    Start-Sleep 5
    try {
        $api = Invoke-RestMethod -Uri 'http://localhost:3000/api' -TimeoutSec 5
        if ($api.version) { $version = $api.version }
    } catch { }
}
if (-not $version) { Fail "Rails did not become healthy in time. Check: docker logs chatwoot-rails-1" }
Step "Chatwoot is up (version $version, queues: $($api.queue_services), data: $($api.data_services))"

# 5. Verify / repair Telegram webhook -----------------------------------------
Step 'Verifying Telegram webhook registration...'
$ruby = @'
expected = ENV.fetch("FRONTEND_URL").chomp("/")
Channel::Telegram.find_each do |ch|
  begin
    info = HTTParty.get("#{ch.telegram_api_url}/getWebhookInfo", timeout: 15).parsed_response["result"]
  rescue StandardError => e
    puts "#{ch.bot_name}: could not reach Telegram (#{e.class}) - retry this step later"
    next
  end
  want = "#{expected}/webhooks/telegram/#{ch.bot_token}"
  masked_actual = (info["url"] || "none").sub(%r{/webhooks/telegram/.*}, "/webhooks/telegram/***")
  if info["url"] != want
    ch.send(:setup_telegram_webhook)
    puts "#{ch.bot_name}: webhook was stale (#{masked_actual}) - re-registered to #{expected}/webhooks/telegram/***"
  else
    puts "#{ch.bot_name}: webhook OK -> #{expected}/webhooks/telegram/***"
  end
end
'@
$ruby | docker exec -i chatwoot-rails-1 bundle exec rails runner -
if ($LASTEXITCODE -ne 0) { Write-Host 'WARNING: webhook verification step failed - run it manually later.' -ForegroundColor Yellow }

Write-Host ''
Write-Host '==> Done. Chatwoot: http://localhost:3000' -ForegroundColor Green
if ($publicUrl) { Write-Host "    Tunnel: $publicUrl" -ForegroundColor Green }
