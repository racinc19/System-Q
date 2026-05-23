param(
    [string]$VerifyText = "A complete musician environment"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$siteDir = Join-Path $repoRoot "Deploy\live"
$projectName = "recording-environment"
$productionBranch = "master"
$liveUrl = "https://recording-environment.pages.dev/"

if (-not (Test-Path -LiteralPath (Join-Path $siteDir "index.html"))) {
    throw "Deploy/live/index.html was not found. Run this script from the repo tools folder."
}

Push-Location $repoRoot
try {
    Write-Host "Deploying $siteDir to Cloudflare Pages project '$projectName' as production branch '$productionBranch'..."
    npx wrangler pages deploy $siteDir --project-name=$projectName --branch=$productionBranch --commit-dirty=true

    Write-Host "Verifying live site contains: $VerifyText"
    $html = (Invoke-WebRequest -Uri $liveUrl -UseBasicParsing -Headers @{ "Cache-Control" = "no-cache" }).Content
    if ($html -notmatch [regex]::Escape($VerifyText)) {
        throw "Live site did not contain '$VerifyText' after deploy: $liveUrl"
    }

    Write-Host "Verified production site: $liveUrl"
}
finally {
    Pop-Location
}
