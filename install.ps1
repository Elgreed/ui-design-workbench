[CmdletBinding()]
param(
    [ValidateSet('all', 'codex', 'claude', 'cursor', 'gemini', 'copilot', 'opencode', 'agents')]
    [string]$Agent = 'all'
)

$ErrorActionPreference = 'Stop'
$skillName = 'ui-design-workbench'
$source = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$userRoot = [Environment]::GetFolderPath('UserProfile')

$targets = [ordered]@{
    agents   = Join-Path $userRoot ".agents\skills\$skillName"
    codex    = Join-Path $userRoot ".codex\skills\$skillName"
    claude   = Join-Path $userRoot ".claude\skills\$skillName"
    cursor   = Join-Path $userRoot ".cursor\skills\$skillName"
    gemini   = Join-Path $userRoot ".gemini\skills\$skillName"
    copilot  = Join-Path $userRoot ".copilot\skills\$skillName"
    opencode = Join-Path $userRoot ".config\opencode\skills\$skillName"
}

function Install-SkillLink([string]$name, [string]$target) {
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if ($resolved -eq $source) {
            Write-Host "${name}: already installed at $target"
            return
        }
        throw "$name target already exists: $target. Move or remove it explicitly, then rerun the installer."
    }
    New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    Write-Host "${name}: installed at $target"
}

$selected = if ($Agent -eq 'all') { @('agents', 'codex', 'claude', 'cursor', 'gemini', 'copilot', 'opencode') } else { @($Agent) }
foreach ($name in $selected) {
    Install-SkillLink $name $targets[$name]
}

Write-Host 'Done. Restart the selected agent or open a new session so it can rediscover the skill.'
