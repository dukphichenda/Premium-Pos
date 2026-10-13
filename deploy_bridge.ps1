# inFlow Premium Enterprise - PowerShell GitHub Sync & Cloudflare Tunnel Bridge
[CmdletBinding()]
param (
    [string]$CommitMessage = "",
    [switch]$StatusOnly
)

$Host.UI.RawUI.WindowTitle = "inFlow Premium - GitHub Sync & Cloudflare Tunnel"

function Write-Header {
    Write-Host ""
    Write-Host "=====================================================================" -ForegroundColor Cyan
    Write-Host "         inFlow Premium Enterprise - Cloud Bridge" -ForegroundColor Yellow
    Write-Host "         GitHub Sync & Cloudflare Remote Access Tunnel" -ForegroundColor White
    Write-Host "=====================================================================" -ForegroundColor Cyan
    Write-Host ""
}

Write-Header

if ($StatusOnly) {
    Write-Host "Current Git Status:" -ForegroundColor Yellow
    git status
    Write-Host "`nConfigured Remotes:" -ForegroundColor Yellow
    git remote -v
    exit 0
}

# Step 1: Git Status Check
$gitStatus = git status --porcelain
if (-not $gitStatus) {
    Write-Host "Working tree is clean. No uncommitted changes." -ForegroundColor Green
} else {
    Write-Host "Changes detected:" -ForegroundColor Yellow
    git status -s
    Write-Host ""
}

# Prompt for message if not passed via parameter
if (-not $CommitMessage) {
    $defaultMsg = "feat: sync inFlow Premium project - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    $inputMsg = Read-Host "Enter commit message (Press Enter for '$defaultMsg')"
    if ([string]::IsNullOrWhiteSpace($inputMsg)) {
        $CommitMessage = $defaultMsg
    } else {
        $CommitMessage = $inputMsg
    }
}

# Stage and Commit
Write-Host "`nStaging all files and committing..." -ForegroundColor Cyan
git add .
$commitResult = git commit -m "$CommitMessage" 2>&1
Write-Host $commitResult -ForegroundColor Gray

# Push to GitHub Remotes
Write-Host "`nPushing to GitHub (origin: dukphichenda/Premium-Pos)..." -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "Successfully pushed to origin (Premium-Pos)!" -ForegroundColor Green
} else {
    Write-Host "Push to origin failed or needs credentials." -ForegroundColor Red
}

Write-Host "`nPushing to GitHub (inflow-repo: dukphichenda/inflow-premium)..." -ForegroundColor Cyan
git push inflow-repo main
if ($LASTEXITCODE -eq 0) {
    Write-Host "Successfully pushed to inflow-repo (inflow-premium)!" -ForegroundColor Green
} else {
    Write-Host "Push to inflow-repo had an issue (may need credentials or already in sync)." -ForegroundColor Yellow
}

Write-Host "`nGitHub upload complete!" -ForegroundColor Green
Write-Host "Repositories:" -ForegroundColor White
Write-Host "  - https://github.com/dukphichenda/Premium-Pos" -ForegroundColor Cyan
Write-Host "  - https://github.com/dukphichenda/inflow-premium" -ForegroundColor Cyan

Write-Host "`nDone!" -ForegroundColor Green
