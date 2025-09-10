# check_manifest.ps1
# Verifies manifest.json key ordering for Home Assistant integrations

Write-Host "Scanning for manifest.json files..."

# Find all manifest.json files
$manifests = Get-ChildItem -Recurse -Filter "manifest.json"

if ($manifests.Count -eq 0) {
    Write-Host "No manifest.json files found"
    exit 1
}

foreach ($file in $manifests) {
    Write-Host ""
    Write-Host "Found: $($file.FullName)"

    try {
        $json = Get-Content $file.FullName | ConvertFrom-Json
        $keys = $json.PSObject.Properties.Name

        Write-Host "   Keys: $($keys -join ', ')"

        # Expected order: domain, name, version, then alphabetical
        $expected = @("domain","name","version") + `
            ($keys | Where-Object {$_ -notin @("domain","name","version")} | Sort-Object)

        if (($keys -join ",") -eq ($expected -join ",")) {
            Write-Host "   Keys are correctly ordered"
        }
        else {
            Write-Host "   Keys are NOT correctly ordered"
            Write-Host "   Expected: $($expected -join ', ')"
        }
    }
    catch {
        Write-Host "   Failed to parse JSON: $_"
    }
}
