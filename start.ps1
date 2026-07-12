# Local start helper — copies .env.example if missing, then runs docker compose.
# Secrets: put Kraken/Telegram values in .env (or inject via Infisical later).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example — edit credentials before going live."
}

docker compose up -d --build
docker compose logs -f --tail=50 bot
