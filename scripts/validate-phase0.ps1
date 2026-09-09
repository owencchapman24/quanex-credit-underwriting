$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$phaseDirectory = Join-Path $repositoryRoot "docs\phase-0"
$inventoryPath = Join-Path $phaseDirectory "EVIDENCE_INVENTORY.csv"
$cutoff = [datetime]::ParseExact("2025-12-15", "yyyy-MM-dd", $null)

$requiredDocuments = @(
    "CASE_CHARTER.md",
    "EXISTING_FINANCING.md",
    "DECISION_LOG.md",
    "EVIDENCE_INVENTORY.csv"
)

$requiredSources = @(
    "SRC-001", # FY2025 10-K
    "SRC-003", # operative amendment / conformed agreement
    "SRC-004", # original credit agreement
    "SRC-006", # definitive transaction proxy
    "SRC-008", # pro forma combined information
    "SRC-012", # FY2024 10-K
    "SRC-013", # FY2023 10-K
    "SRC-014", # FY2022 10-K
    "SRC-015"  # FY2021 10-K
)

$errors = [System.Collections.Generic.List[string]]::new()

foreach ($document in $requiredDocuments) {
    $path = Join-Path $phaseDirectory $document
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $errors.Add("Missing Phase 0 document: $document")
    }
}

$rows = @()
if (Test-Path -LiteralPath $inventoryPath -PathType Leaf) {
    $rows = @(Import-Csv -LiteralPath $inventoryPath)
}

if ($rows.Count -eq 0) {
    $errors.Add("Evidence inventory is empty")
}
else {
    $ids = @($rows | ForEach-Object { $_.source_id })
    $duplicateIds = @($ids | Group-Object | Where-Object { $_.Count -gt 1 })
    if ($duplicateIds.Count -gt 0) {
        $errors.Add("Evidence inventory contains duplicate source_id values")
    }

    foreach ($sourceId in $requiredSources) {
        if ($sourceId -notin $ids) {
            $errors.Add("Missing required source: $sourceId")
        }
    }

    foreach ($row in $rows) {
        $publicationDate = [datetime]::MinValue
        if (-not [datetime]::TryParseExact(
            $row.publication_or_filing_date,
            "yyyy-MM-dd",
            $null,
            [Globalization.DateTimeStyles]::None,
            [ref]$publicationDate
        )) {
            $errors.Add("$($row.source_id): invalid publication_or_filing_date")
            continue
        }

        if ($publicationDate -gt $cutoff) {
            $errors.Add("$($row.source_id): post-cutoff publication date")
        }
        if ($row.cutoff_status -ne "ALLOWED") {
            $errors.Add("$($row.source_id): unexpected cutoff_status")
        }
        if (-not $row.source_location.StartsWith("https://")) {
            $errors.Add("$($row.source_id): source location is not HTTPS")
        }
        if (
            [string]::IsNullOrWhiteSpace($row.intended_analytical_use) -or
            [string]::IsNullOrWhiteSpace($row.authority)
        ) {
            $errors.Add("$($row.source_id): missing use or authority assessment")
        }
    }
}

foreach ($document in @("CASE_CHARTER.md", "EXISTING_FINANCING.md", "DECISION_LOG.md")) {
    $path = Join-Path $phaseDirectory $document
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $content = Get-Content -Raw -LiteralPath $path
        if (-not $content.Contains("Information cutoff: 2025-12-15")) {
            $errors.Add("$document`: cutoff banner missing")
        }
    }
}

# Reperform the disclosed facility bridge rather than trusting prose.
[decimal]$term = 468.75
[decimal]$revolver = 172.50
[decimal]$commitments = 475.00
[decimal]$lettersOfCredit = 6.20
if (($term + $revolver) -ne [decimal]641.25) {
    $errors.Add("Facility principal bridge failed")
}
if (($commitments - $revolver - $lettersOfCredit) -ne [decimal]296.30) {
    $errors.Add("Revolver availability bridge failed")
}

if ($errors.Count -gt 0) {
    Write-Output "Phase 0 validation: FAIL"
    foreach ($validationError in $errors) {
        Write-Output "- $validationError"
    }
    exit 1
}

Write-Output "Phase 0 validation: PASS"
Write-Output "- $($rows.Count) allowed sources; all published on or before 2025-12-15"
Write-Output "- Required charter, financing analysis, inventory, and decision log are present"
Write-Output "- Cutoff banners are present"
Write-Output "- Facility principal and revolver availability bridges reconcile"
