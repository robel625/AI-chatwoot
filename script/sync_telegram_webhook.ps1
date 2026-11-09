# script/sync_telegram_webhook.ps1
# Synchronizes active ngrok public endpoint with Chatwoot .env and Telegram Bot webhook.

$ngrokApi = "http://127.0.0.1:4040/api/tunnels"
try {
    $response = Invoke-RestMethod -Uri $ngrokApi -Method Get -TimeoutSec 3 -ErrorAction Stop
} catch {
    Write-Host "[ERROR] ngrok is not reachable at $ngrokApi. Please ensure 'ngrok http 3000' is running." -ForegroundColor Red
    exit 1
}

$tunnel = $response.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
if (-not $tunnel -or -not $tunnel.public_url) {
    Write-Host "[ERROR] No active HTTPS tunnel found in ngrok." -ForegroundColor Red
    exit 1
}

$publicUrl = $tunnel.public_url
Write-Host "[INFO] Active ngrok public URL: $publicUrl" -ForegroundColor Cyan

# 1. Update Chatwoot .env FRONTEND_URL if needed
$envPath = "C:\Users\robel\Downloads\chatwoot\.env"
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath -Raw
    $pattern = '(?m)^FRONTEND_URL=.*$'
    $targetLine = "FRONTEND_URL=$publicUrl"
    if ($envContent -match $pattern) {
        $currentVal = ($envContent | Select-String $pattern).Matches.Value
        if ($currentVal -ne $targetLine) {
            $updatedContent = $envContent -replace $pattern, $targetLine
            Set-Content -Path $envPath -Value $updatedContent -NoNewline
            Write-Host "[INFO] Updated FRONTEND_URL in .env -> $targetLine" -ForegroundColor Green
        } else {
            Write-Host "[INFO] FRONTEND_URL in .env is already up to date." -ForegroundColor Green
        }
    }
}

# 2. Sync Telegram Webhook in Chatwoot container via stdin
Write-Host "[INFO] Syncing Telegram webhook in chatwoot-rails-1..." -ForegroundColor Cyan
$rubyCode = @"
telegram = Channel::Telegram.first
if telegram
  token = telegram.bot_token
  target_url = "$publicUrl/webhooks/telegram/#{token}"
  res = HTTParty.post("https://api.telegram.org/bot#{token}/setWebhook", body: { url: target_url })
  puts "Telegram setWebhook response: #{res.body}"
else
  puts "No Telegram channel configured in Chatwoot."
end
"@

$output = $rubyCode | docker exec -i chatwoot-rails-1 bundle exec rails runner -
Write-Host $output -ForegroundColor Yellow

Write-Host "[SUCCESS] Telegram webhook synced successfully to $publicUrl" -ForegroundColor Green
