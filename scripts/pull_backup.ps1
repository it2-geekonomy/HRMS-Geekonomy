# Pull latest Horilla full backup (DB dump + media) from DigitalOcean to this PC.
# Schedule with Windows Task Scheduler daily (e.g. 12:30 AM IST).

param(
    [string]$DropletHost = "165.232.181.113",
    [string]$RemoteUser = "root",
    [string]$RemoteDir = "/opt/hrms/backups",
    [string]$LocalDir = "C:\Geekonomy HRMS\hrms\backups",
    [ValidateSet("bundle", "separate", "db-only")]
    [string]$Mode = "separate"  # separate = dump + media; bundle = one .tar; db-only = dump only
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $LocalDir "pull_backup.log"

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line
    Write-Host $line
}

function Pull-File([string]$remoteName, [string]$localName) {
    $dest = Join-Path $LocalDir $localName
    Write-Log "scp ${remoteName} -> ${dest}"
    & scp.exe "${RemoteUser}@${DropletHost}:${RemoteDir}/${remoteName}" $dest
    if (-not (Test-Path $dest)) {
        throw "Missing after scp: $dest"
    }
    return $dest
}

Write-Log "Pull start mode=$Mode from ${RemoteUser}@${DropletHost}:${RemoteDir}"

switch ($Mode) {
    "bundle" {
        $bundle = Pull-File "horilla_full_latest.tar" "horilla_full_latest.tar"
        $dated = Join-Path $LocalDir "horilla_full_${stamp}.tar"
        Copy-Item $bundle $dated -Force
        Write-Log "Saved $bundle and $dated"
    }
    "db-only" {
        $dump = Pull-File "horilla_latest.dump" "horilla_latest.dump"
        $dated = Join-Path $LocalDir "horilla_${stamp}.dump"
        Copy-Item $dump $dated -Force
        Write-Log "Saved $dump and $dated"
    }
    default {
        $dump = Pull-File "horilla_latest.dump" "horilla_latest.dump"
        $media = Pull-File "horilla_media_latest.tar.gz" "horilla_media_latest.tar.gz"
        Copy-Item $dump (Join-Path $LocalDir "horilla_${stamp}.dump") -Force
        Copy-Item $media (Join-Path $LocalDir "horilla_media_${stamp}.tar.gz") -Force
        Write-Log "Saved DB + media (latest and dated $stamp)"
    }
}

# Keep 14 local dated copies of each type
foreach ($filter in @("horilla_20*.dump", "horilla_media_20*.tar.gz", "horilla_full_20*.tar")) {
    Get-ChildItem $LocalDir -Filter $filter |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 14 |
        ForEach-Object {
            Write-Log "Prune local $($_.Name)"
            Remove-Item $_.FullName -Force
        }
}

Write-Log "Pull done"
