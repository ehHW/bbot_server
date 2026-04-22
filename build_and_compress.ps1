$ErrorActionPreference = 'Stop'
Write-Host '========================================' -ForegroundColor Green
Write-Host 'Hyself Docker Build & Compress' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green

$projectDir = 'D:\work\SolBot\hyself_server'
Set-Location $projectDir
Write-Host "Project Directory: $projectDir" -ForegroundColor Green

$imageTag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { '1.0.0' }
Write-Host "Using image tag: $imageTag" -ForegroundColor Green

Write-Host ''
Write-Host 'Checking docker compose...' -ForegroundColor Cyan
docker compose version

Write-Host ''
Write-Host 'Building images...' -ForegroundColor Cyan
docker compose build --no-cache

Write-Host ''
Write-Host 'Built images:' -ForegroundColor Cyan
docker images | Select-String 'hyself_server'

Write-Host ''
Write-Host 'Saving images to tar...' -ForegroundColor Cyan
# Adjusting image names based on the original script's intent
docker save hyself_server-backend:$imageTag hyself_server-celery:$imageTag hyself_server-db:$imageTag hyself_server-redis:$imageTag -o hyself_images.tar

Write-Host ''
Write-Host 'Compressing archive...' -ForegroundColor Cyan
$sevenZipPath = 'C:\Program Files\7-Zip\7z.exe'
if (Test-Path $sevenZipPath) {
    & $sevenZipPath a -tgzip hyself_images.tar.gz hyself_images.tar
    if ($LASTEXITCODE -ne 0) {
        throw '7-Zip compression failed.'
    }
    Remove-Item hyself_images.tar -Force
    $archivePath = 'hyself_images.tar.gz'
}
else {
    Write-Host '7-Zip not found, using Compress-Archive to create .zip' -ForegroundColor Yellow
    Compress-Archive -Path hyself_images.tar -DestinationPath hyself_images.tar.zip -Force
    Remove-Item hyself_images.tar -Force
    $archivePath = 'hyself_images.tar.zip'
}

Write-Host ''
Write-Host '========================================' -ForegroundColor Green
Write-Host 'Build & Compress Complete' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green
$fileInfo = Get-Item $archivePath
Write-Host "File: $($fileInfo.Name)" -ForegroundColor Yellow
Write-Host "Size: $([math]::Round($fileInfo.Length / 1MB, 2)) MB" -ForegroundColor Yellow
