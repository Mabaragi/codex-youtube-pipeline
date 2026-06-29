param(
    [Parameter(Mandatory = $true)][int]$VideoId,
    [Parameter(Mandatory = $true)][int]$VideoTaskId,
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Instruction,
    [string]$SpecPath,
    [string]$AnchorEpisodeId,
    [string]$AnchorTimecode,
    [string]$AnchorDisplayTitle,
    [string]$AnchorDisplaySummary,
    [string]$NewBlockType = "POST_GAME",
    [string]$NewBlockTitle,
    [string]$NewBlockSummary,
    [string]$NewBlockDisplayTitle,
    [string]$NewBlockDisplaySummary,
    [switch]$Apply,
    [switch]$Publish,
    [string]$Environment = "prod",
    [string]$Variant = "control",
    [int]$SchemaVersion = 1,
    [switch]$VerifyPublic
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

function Copy-JsonObject {
    param([Parameter(Mandatory = $true)][object]$Value)
    return $Value | ConvertTo-Json -Depth 100 | ConvertFrom-Json
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [object]$Value
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        $property.Value = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function New-SplitPatchRequest {
    if (-not $AnchorEpisodeId -and -not $AnchorTimecode -and -not $AnchorDisplayTitle -and -not $AnchorDisplaySummary) {
        throw "Provide -AnchorEpisodeId or at least one anchor matcher (-AnchorTimecode/-AnchorDisplayTitle/-AnchorDisplaySummary)."
    }

    $operation = [ordered]@{
        operation = "split_block_after_episode"
    }
    if ($AnchorEpisodeId) {
        $operation.anchorEpisodeId = $AnchorEpisodeId
    } else {
        $anchor = [ordered]@{}
        if ($AnchorTimecode) { $anchor.timecode = $AnchorTimecode }
        if ($AnchorDisplayTitle) { $anchor.displayTitle = $AnchorDisplayTitle }
        if ($AnchorDisplaySummary) { $anchor.displaySummary = $AnchorDisplaySummary }
        $operation.anchor = $anchor
    }

    $newBlock = [ordered]@{}
    if ($NewBlockType) { $newBlock.blockType = $NewBlockType }
    if ($NewBlockTitle) { $newBlock.title = $NewBlockTitle }
    if ($NewBlockSummary) { $newBlock.summary = $NewBlockSummary }
    if ($NewBlockDisplayTitle) { $newBlock.displayTitle = $NewBlockDisplayTitle }
    if ($NewBlockDisplaySummary) { $newBlock.displaySummary = $NewBlockDisplaySummary }
    if ($newBlock.Count -gt 0) {
        $operation.newBlock = $newBlock
    }

    return [ordered]@{
        dryRun = $true
        instruction = $Instruction
        operations = @($operation)
    }
}

function Get-ChangedBlockIds {
    param([Parameter(Mandatory = $true)][object]$Response)
    $ids = New-Object System.Collections.Generic.List[string]
    foreach ($operation in @($Response.operations)) {
        foreach ($blockId in @($operation.changedBlockIds)) {
            if ($blockId -and -not $ids.Contains([string]$blockId)) {
                $ids.Add([string]$blockId)
            }
        }
        if ($operation.newBlockId -and -not $ids.Contains([string]$operation.newBlockId)) {
            $ids.Add([string]$operation.newBlockId)
        }
    }
    return @($ids)
}

function Select-PatchSummary {
    param(
        [Parameter(Mandatory = $true)][object]$Response,
        [int[]]$PublicHeadStatus = @()
    )

    $changedBlockIds = @(Get-ChangedBlockIds $Response)
    $afterBlocks = @($Response.after.blocks)
    $blocks = @(
        if ($changedBlockIds.Count -gt 0) {
            $afterBlocks | Where-Object { $changedBlockIds -contains $_.blockId }
        } else {
            $afterBlocks | Select-Object -Last 5
        }
    )

    return [ordered]@{
        dryRun = $Response.dryRun
        applied = $Response.applied
        videoId = $Response.videoId
        videoTaskId = $Response.videoTaskId
        timelineCompositionId = $Response.timelineCompositionId
        operationCount = @($Response.operations).Count
        changedBlockIds = $changedBlockIds
        changedBlocks = @(
            $blocks | ForEach-Object {
                [ordered]@{
                    blockId = $_.blockId
                    blockIndex = $_.blockIndex
                    blockType = $_.blockType
                    displayTitle = $_.displayTitle
                    displaySummary = $_.displaySummary
                    episodeIds = @($_.episodeIds)
                }
            }
        )
        validationWarningCount = @($Response.validationWarnings).Count
        publishSummary = $Response.publishSummary
        publicHeadStatus = $PublicHeadStatus
    }
}

function Test-PublicUrl {
    param([string]$Url)
    if (-not $Url) {
        return @()
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $Url -Headers @{
            "User-Agent" = "Mozilla/5.0"
        } -TimeoutSec 20
        return @([int]$response.StatusCode)
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return @([int]$_.Exception.Response.StatusCode)
        }
        return @(-1)
    }
}

if ($SpecPath) {
    $resolvedSpecPath = (Resolve-Path -LiteralPath $SpecPath).Path
    $request = Get-Content -Encoding UTF8 -Raw -LiteralPath $resolvedSpecPath | ConvertFrom-Json
} else {
    $request = New-SplitPatchRequest
}

$uri = "$BaseUrl/videos/$VideoId/timelines/$VideoTaskId/patch"

$dryRunRequest = Copy-JsonObject $request
Set-JsonProperty $dryRunRequest "dryRun" $true
Set-JsonProperty $dryRunRequest "publish" $null
$dryRunResponse = Invoke-JsonUtf8 -Method Post -Uri $uri -Body $dryRunRequest -Depth 100

if (-not $Apply) {
    Select-PatchSummary $dryRunResponse | ConvertTo-Json -Depth 100
    exit 0
}

$applyRequest = Copy-JsonObject $request
Set-JsonProperty $applyRequest "dryRun" $false
if ($Publish) {
    Set-JsonProperty $applyRequest "publish" ([ordered]@{
        enabled = $true
        environment = $Environment
        variant = $Variant
        schemaVersion = $SchemaVersion
    })
}

$applyResponse = Invoke-JsonUtf8 -Method Post -Uri $uri -Body $applyRequest -Depth 100
$publicHeadStatus = @()
if ($VerifyPublic -and $applyResponse.publishSummary -and $applyResponse.publishSummary.publicUrl) {
    $publicHeadStatus = @(Test-PublicUrl $applyResponse.publishSummary.publicUrl)
}

[ordered]@{
    dryRun = Select-PatchSummary $dryRunResponse
    apply = Select-PatchSummary $applyResponse -PublicHeadStatus $publicHeadStatus
} | ConvertTo-Json -Depth 100
