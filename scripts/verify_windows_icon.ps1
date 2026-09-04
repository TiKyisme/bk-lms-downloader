param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [string]$SourcePngPath = "BK-LMS-Downloader-icon-blue.png"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$ResolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$ResolvedSource = (Resolve-Path -LiteralPath $SourcePngPath).Path
$ActualIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($ResolvedExe)
if ($null -eq $ActualIcon) {
    throw "Windows executable does not expose an application icon: $ResolvedExe"
}

$ActualBitmap = $ActualIcon.ToBitmap()
$SourceBitmap = New-Object System.Drawing.Bitmap($ResolvedSource)
$ExpectedBitmap = New-Object System.Drawing.Bitmap($SourceBitmap, 32, 32)
try {
    $Difference = 0L
    $Samples = 0L
    for ($Y = 0; $Y -lt 32; $Y++) {
        for ($X = 0; $X -lt 32; $X++) {
            $Actual = $ActualBitmap.GetPixel($X, $Y)
            $Expected = $ExpectedBitmap.GetPixel($X, $Y)
            $Difference += [Math]::Abs([int]$Actual.R - [int]$Expected.R)
            $Difference += [Math]::Abs([int]$Actual.G - [int]$Expected.G)
            $Difference += [Math]::Abs([int]$Actual.B - [int]$Expected.B)
            $Difference += [Math]::Abs([int]$Actual.A - [int]$Expected.A)
            $Samples += 4
        }
    }
    $MeanDifference = $Difference / $Samples
    if ($MeanDifference -gt 25) {
        throw "Embedded executable icon does not match the project icon (mean channel difference: $MeanDifference)."
    }
    Write-Host "Windows icon verification OK (mean channel difference: $MeanDifference)"
}
finally {
    $ActualBitmap.Dispose()
    $ExpectedBitmap.Dispose()
    $SourceBitmap.Dispose()
    $ActualIcon.Dispose()
}
