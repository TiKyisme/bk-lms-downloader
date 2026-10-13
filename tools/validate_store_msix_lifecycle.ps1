[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$identityName = 'TiKyisme.BK-LMSDownloader'
$publisher = 'CN=73CAA01F-F63A-4EAE-BDD2-53B50789E666'
$applicationId = 'BKLMSDOWNLOADER'
$familyName = 'TiKyisme.BK-LMSDownloader_ss3k4ggr3cwng'
$aumid = "$familyName!$applicationId"
$candidateVersion = '1.5.2.0'
$legacyVersion = '1.3.0.0'
$exeName = 'BK-LMS-Downloader.exe'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$testRoot = Join-Path $env:RUNNER_TEMP 'bklms-store-msix-lifecycle'
$resultPath = Join-Path $testRoot 'result.json'
$script:state = [ordered]@{
    runner_os = $null
    runner_admin = $false
    uac = $null
    makeappx = $null
    signtool = $null
    appx_service = $null
    candidate_file = $null
    candidate_version = $candidateVersion
    candidate_bytes = $null
    candidate_sha256 = $null
    candidate_signed = $false
    candidate_identity = $null
    candidate_family = $null
    candidate_aumid = $null
    clean_install = 'NOT_RUN'
    installed_exe = 'NOT_RUN'
    aumid_registration = 'NOT_RUN'
    startapps_lookup = 'NOT_RUN'
    clean_install_aumid_launch = 'NOT_RUN'
    synthetic_legacy_version = $legacyVersion
    synthetic_legacy_install = 'NOT_RUN'
    legacy_shortcut_manifest = 'NOT_RUN'
    legacy_shortcut_target = $null
    legacy_version_bound_shortcut = 'NOT_CONFIRMED'
    update_in_place = 'NOT_RUN'
    post_update_version = $null
    stale_shortcut_after_update = 'NOT_CONFIRMED'
    post_update_aumid_launch = 'NOT_RUN'
    recovery_model = 'NOT_RUN'
    fixed_fresh_install_shortcut = 'NOT_RUN'
    wack = 'NOT RUN'
    failure = $null
    cleanup = 'NOT_RUN'
}

$testCertificateThumbprint = $null
$script:ownedTestPackageLifecycle = $false
$script:testProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$createdShortcutPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$candidate = $null
$appCertPath = $null

function Get-BkShortcuts {
    $folders = @(
        [Environment]::GetFolderPath('Desktop'),
        [Environment]::GetFolderPath('CommonDesktopDirectory'),
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    foreach ($folder in $folders) {
        Get-ChildItem -LiteralPath $folder -Filter 'BK-LMS Downloader.lnk' -File -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName }
    }
}

function Get-ShortcutTarget([string]$path) {
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($path)
        return [string]$shortcut.TargetPath
    }
    finally {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}

function Get-InstalledTargetPackage {
    return Get-AppxPackage -Name $identityName -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Assert-InstalledPackage([string]$expectedVersion) {
    $package = Get-InstalledTargetPackage
    if (-not $package) { throw "Expected package $identityName is not registered." }
    if ([string]$package.Version -ne $expectedVersion) {
        throw "Expected package version $expectedVersion; found $($package.Version)."
    }
    if ([string]$package.PackageFamilyName -ne $familyName) {
        throw "Unexpected package family: $($package.PackageFamilyName)."
    }
    $installedExe = Join-Path $package.InstallLocation $exeName
    if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) {
        throw "Installed executable is missing: $installedExe"
    }
    return $package
}

function Get-StartAppMatch {
    if (-not (Get-Command Get-StartApps -ErrorAction SilentlyContinue)) {
        return $null
    }
    try {
        return Get-StartApps -ErrorAction Stop |
            Where-Object { $_.AppID -eq $aumid } |
            Select-Object -First 1
    }
    catch {
        return $null
    }
}

function Test-AumidLaunch([string]$installLocation, [string]$stage) {
    $sessionId = (Get-Process -Id $PID).SessionId
    $explorer = Get-Process -Name explorer -ErrorAction SilentlyContinue |
        Where-Object { $_.SessionId -eq $sessionId } |
        Select-Object -First 1
    if ($sessionId -eq 0 -or -not $explorer) {
        Write-Host "$stage AUMID launch skipped: no interactive Explorer session (session $sessionId)."
        return 'ENVIRONMENT_LIMITATION'
    }

    $before = @(Get-CimInstance Win32_Process -Filter "Name='$exeName'" -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.ProcessId })
    try {
        Start-Process -FilePath (Join-Path $env:WINDIR 'explorer.exe') `
            -ArgumentList "shell:AppsFolder\$aumid" -ErrorAction Stop | Out-Null
    }
    catch {
        Write-Host "$stage AUMID launch request failed: $($_.Exception.Message)"
        return 'FAIL'
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(35)
    $launched = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $launched = Get-CimInstance Win32_Process -Filter "Name='$exeName'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                $_.ExecutablePath.StartsWith($installLocation, [StringComparison]::OrdinalIgnoreCase) -and
                [int]$_.ProcessId -notin $before
            } |
            Select-Object -First 1
        if ($launched) { break }
        Start-Sleep -Seconds 1
    }

    if (-not $launched) {
        Write-Host "$stage AUMID launch did not produce a process in the installed package path."
        return 'FAIL'
    }

    [void]$script:testProcessIds.Add([int]$launched.ProcessId)
    Write-Host "$stage AUMID launch process observed: PID $($launched.ProcessId); executable path matches installed package."
    Start-Sleep -Seconds 2
    $stillRunning = Get-CimInstance Win32_Process -Filter "ProcessId=$($launched.ProcessId)" -ErrorAction SilentlyContinue
    if ($stillRunning -and $stillRunning.ExecutablePath -and
        $stillRunning.ExecutablePath.StartsWith($installLocation, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Process -Id ([int]$launched.ProcessId) -Force -ErrorAction SilentlyContinue
        [void]$script:testProcessIds.Remove([int]$launched.ProcessId)
    }
    return 'PASS'
}

function Sign-TestPackage([string]$path, [string]$signToolPath, [string]$thumbprint) {
    & $signToolPath sign /fd SHA256 /sm /s My /sha1 $thumbprint $path
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed signing $([IO.Path]::GetFileName($path)) with exit code $LASTEXITCODE." }
    $script:state.candidate_signed = $true
}

function Write-RunSummary {
    $json = $script:state | ConvertTo-Json -Depth 6
    $json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host 'STORE_MSIX_LIFECYCLE_RESULT_BEGIN'
    Write-Host $json
    Write-Host 'STORE_MSIX_LIFECYCLE_RESULT_END'
    if ($env:GITHUB_STEP_SUMMARY) {
        $lines = @(
            '# Store MSIX lifecycle validation',
            '',
            "- Runner admin: $($script:state.runner_admin)",
            "- Candidate: $($script:state.candidate_version) / $($script:state.candidate_bytes) bytes / SHA256 $($script:state.candidate_sha256)",
            "- Clean install: $($script:state.clean_install)",
            "- Installed EXE: $($script:state.installed_exe)",
            "- AUMID registration: $($script:state.aumid_registration)",
            "- AUMID process launch: $($script:state.clean_install_aumid_launch)",
            "- Synthetic 1.3.0.0 install: $($script:state.synthetic_legacy_install)",
            "- Legacy shortcut target: $($script:state.legacy_shortcut_target)",
            "- Legacy version-bound shortcut: $($script:state.legacy_version_bound_shortcut)",
            "- Update in place: $($script:state.update_in_place)",
            "- Stale shortcut after update: $($script:state.stale_shortcut_after_update)",
            "- Fixed fresh-install shortcut check: $($script:state.fixed_fresh_install_shortcut)",
            "- WACK: $($script:state.wack)",
            "- Failure: $($script:state.failure)",
            "- Cleanup: $($script:state.cleanup)"
        )
        Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value ($lines -join [Environment]::NewLine)
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    Write-Host '--- GitHub-hosted Windows runner context ---'
    & whoami.exe
    & whoami.exe /groups
    Write-Host ([Environment]::OSVersion | Out-String)
    $computer = Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber
    Write-Host ($computer | Format-List | Out-String)

    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $script:state.runner_admin = [bool]$isAdmin
    if (-not $isAdmin) { throw 'Hosted runner is not in an administrative context; refusing certificate/package operations.' }
    $uac = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction SilentlyContinue
    if ($uac) {
        $script:state.uac = "EnableLUA=$($uac.EnableLUA); ConsentPromptBehaviorAdmin=$($uac.ConsentPromptBehaviorAdmin)"
    }
    $script:state.runner_os = "$($computer.WindowsProductName) $($computer.WindowsVersion) build $($computer.OsBuildNumber)"

    foreach ($commandName in @('Add-AppxPackage', 'Get-AppxPackage', 'New-SelfSignedCertificate', 'Export-Certificate', 'Import-Certificate')) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "Required Windows command is unavailable: $commandName"
        }
    }
    $appxService = Get-Service -Name AppXSvc -ErrorAction SilentlyContinue
    if (-not $appxService) { throw 'AppX Deployment Service (AppXSvc) is unavailable.' }
    $script:state.appx_service = "$($appxService.Status); $($appxService.StartType)"

    $sdkRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'),
        (Join-Path $env:ProgramFiles 'Windows Kits\10\bin')
    )
    $makeAppxCandidates = @(
        foreach ($sdkRoot in $sdkRoots) {
            if (Test-Path -LiteralPath $sdkRoot) {
                Get-ChildItem -LiteralPath $sdkRoot -Filter 'MakeAppx.exe' -File -Recurse -ErrorAction SilentlyContinue |
                    Where-Object { $_.FullName -match '[\\/]x64[\\/]MakeAppx\.exe$' }
            }
        }
    )
    $makeAppx = $makeAppxCandidates |
        Sort-Object { try { [Version]$_.Directory.Parent.Name } catch { [Version]'0.0' } } -Descending |
        Select-Object -First 1
    if (-not $makeAppx) { throw "MakeAppx.exe not found under: $($sdkRoots -join ', ')" }
    $signToolPath = Join-Path $makeAppx.DirectoryName 'SignTool.exe'
    if (-not (Test-Path -LiteralPath $signToolPath)) { throw "SignTool.exe not found beside $($makeAppx.FullName)." }
    $script:state.makeappx = $makeAppx.FullName
    $script:state.signtool = $signToolPath
    $script:state.appcert = 'NOT FOUND'
    $appCertRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\App Certification Kit'),
        (Join-Path $env:ProgramFiles 'Windows Kits\10\App Certification Kit')
    )
    foreach ($appCertRoot in $appCertRoots) {
        $candidateAppCert = Join-Path $appCertRoot 'appcert.exe'
        if (Test-Path -LiteralPath $candidateAppCert) { $appCertPath = $candidateAppCert; break }
    }
    if ($appCertPath) { $script:state.appcert = $appCertPath }

    $preexistingPackages = @(Get-AppxPackage -AllUsers -Name $identityName -ErrorAction SilentlyContinue)
    if ($preexistingPackages.Count -gt 0) {
        throw "Fresh runner unexpectedly has package identity installed; refusing to remove it: $($preexistingPackages.PackageFullName -join ', ')"
    }
    $baselineShortcuts = @(Get-BkShortcuts)
    if ($baselineShortcuts.Count -gt 0) {
        throw "Fresh runner has preexisting BK-LMS Downloader shortcuts; refusing to alter them: $($baselineShortcuts -join ', ')"
    }
    $script:ownedTestPackageLifecycle = $true

    $seedPackage = Join-Path $testRoot 'synthetic-identity-seed.msix'
    $candidateDirectory = Join-Path $testRoot 'candidate'
    $seedGenerator = Join-Path $repoRoot 'tools\create_msix_lifecycle_seed.py'
    & python $seedGenerator --output $seedPackage
    if ($LASTEXITCODE -ne 0) { throw "Synthetic identity seed generation failed with exit code $LASTEXITCODE." }
    New-Item -ItemType Directory -Path $candidateDirectory -Force | Out-Null
    & python (Join-Path $repoRoot 'tools\build_msix.py') `
        --identity-package $seedPackage `
        --makeappx $makeAppx.FullName `
        --output $candidateDirectory `
        --local-test-version $candidateVersion
    if ($LASTEXITCODE -ne 0) { throw "Local 1.5.2.0 candidate build failed with exit code $LASTEXITCODE." }

    $candidate = Join-Path $candidateDirectory "BK-LMS-Downloader_${candidateVersion}_x64.msix"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Expected candidate was not built: $candidate" }
    $script:state.candidate_file = [IO.Path]::GetFileName($candidate)
    $script:state.candidate_bytes = (Get-Item -LiteralPath $candidate).Length

    $candidateUnpacked = Join-Path $testRoot 'candidate-unpacked'
    & $makeAppx.FullName unpack /p $candidate /d $candidateUnpacked
    if ($LASTEXITCODE -ne 0) { throw "MakeAppx could not unpack candidate; exit code $LASTEXITCODE." }
    $manifestPath = Join-Path $candidateUnpacked 'AppxManifest.xml'
    [xml]$manifest = Get-Content -LiteralPath $manifestPath -Raw
    $identityNode = $manifest.SelectSingleNode("/*[local-name()='Package']/*[local-name()='Identity']")
    $appNode = $manifest.SelectSingleNode("/*[local-name()='Package']/*[local-name()='Applications']/*[local-name()='Application']")
    if (-not $identityNode -or -not $appNode) { throw 'Candidate manifest is missing identity/application nodes.' }
    if ($identityNode.GetAttribute('Name') -ne $identityName -or
        $identityNode.GetAttribute('Publisher') -ne $publisher -or
        $identityNode.GetAttribute('Version') -ne $candidateVersion -or
        $identityNode.GetAttribute('ProcessorArchitecture') -ne 'x64' -or
        $appNode.GetAttribute('Id') -ne $applicationId) {
        throw 'Candidate manifest identity/version/architecture/Application Id did not match the required values.'
    }
    $manifestText = Get-Content -LiteralPath $manifestPath -Raw
    if ($manifestText -match 'desktop7:Shortcut|WindowsApps|TiKyisme\.BK-LMSDownloader_\d+\.\d+\.\d+\.\d+_x64__') {
        throw 'Fixed candidate manifest contains a shortcut extension or version-specific WindowsApps path.'
    }
    $script:state.candidate_identity = $identityNode.GetAttribute('Name')
    $script:state.candidate_family = $familyName
    $script:state.candidate_aumid = $aumid

    $certificate = New-SelfSignedCertificate -Type Custom `
        -Subject $publisher `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -CertStoreLocation 'Cert:\LocalMachine\My' `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
    if ($certificate.Subject -ne $publisher) { throw 'Ephemeral certificate subject does not exactly match manifest Publisher.' }
    $testCertificateThumbprint = $certificate.Thumbprint
    $publicCertPath = Join-Path $testRoot 'ephemeral-test-publisher.cer'
    Export-Certificate -Cert $certificate -FilePath $publicCertPath -Force | Out-Null
    Import-Certificate -FilePath $publicCertPath -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
    Sign-TestPackage -path $candidate -signToolPath $signToolPath -thumbprint $testCertificateThumbprint
    $signatureCheck = & $signToolPath verify /pa /v $candidate 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SignTool signature verification failed: $($signatureCheck | Out-String)" }
    $candidateHash = Get-FileHash -LiteralPath $candidate -Algorithm SHA256
    $script:state.candidate_sha256 = $candidateHash.Hash
    $script:state.candidate_bytes = (Get-Item -LiteralPath $candidate).Length
    Write-Host "Signed candidate: $($script:state.candidate_file); $($script:state.candidate_bytes) bytes; SHA256 $($script:state.candidate_sha256)."

    $script:state.clean_install = 'FAIL'
    $script:state.installed_exe = 'FAIL'
    Add-AppxPackage -Path $candidate -ErrorAction Stop
    $package = Assert-InstalledPackage $candidateVersion
    $script:state.clean_install = 'PASS'
    $script:state.installed_exe = 'PASS'
    $startApp = Get-StartAppMatch
    if (-not (Get-Command Get-StartApps -ErrorAction SilentlyContinue)) {
        $script:state.startapps_lookup = 'ENVIRONMENT_LIMITATION: Get-StartApps unavailable; package registration and manifest AUMID verified'
        $script:state.aumid_registration = 'PASS (package identity and manifest Application Id)'
    }
    elseif ($startApp -and $startApp.AppID -eq $aumid) {
        $script:state.startapps_lookup = 'PASS'
        $script:state.aumid_registration = 'PASS'
    }
    else {
        $script:state.startapps_lookup = 'FAIL: expected AUMID absent'
        $script:state.aumid_registration = 'FAIL'
        throw 'Installed package did not appear in Get-StartApps with the expected AUMID.'
    }
    $script:state.clean_install_aumid_launch = Test-AumidLaunch -installLocation $package.InstallLocation -stage 'Clean-install'

    Remove-AppxPackage -Package $package.PackageFullName -ErrorAction Stop
    if (Get-InstalledTargetPackage) { throw 'Could not remove the test candidate before installing the synthetic legacy package.' }

    $legacyPayload = Join-Path $testRoot 'legacy-payload'
    $legacyOutput = Join-Path $testRoot 'legacy'
    New-Item -ItemType Directory -Path $legacyPayload, $legacyOutput -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $candidateUnpacked $exeName) -Destination (Join-Path $legacyPayload $exeName)
    Copy-Item -LiteralPath (Join-Path $candidateUnpacked 'Assets') -Destination (Join-Path $legacyPayload 'Assets') -Recurse

    $legacyManifest = New-Object Xml.XmlDocument
    $legacyManifest.PreserveWhitespace = $false
    $legacyManifest.Load($manifestPath)
    $foundationNs = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'
    $desktop7Ns = 'http://schemas.microsoft.com/appx/manifest/desktop/windows10/7'
    $legacyRoot = $legacyManifest.DocumentElement
    $legacyRoot.SetAttribute('IgnorableNamespaces', 'uap rescap desktop7')
    $desktopNsAttribute = $legacyManifest.CreateAttribute('xmlns', 'desktop7', 'http://www.w3.org/2000/xmlns/')
    $desktopNsAttribute.Value = $desktop7Ns
    [void]$legacyRoot.Attributes.Append($desktopNsAttribute)
    $legacyIdentity = $legacyManifest.SelectSingleNode("/*[local-name()='Package']/*[local-name()='Identity']")
    $legacyIdentity.SetAttribute('Version', $legacyVersion)
    $legacyApp = $legacyManifest.SelectSingleNode("/*[local-name()='Package']/*[local-name()='Applications']/*[local-name()='Application']")
    $extensions = $legacyManifest.CreateElement('', 'Extensions', $foundationNs)
    $shortcutExtension = $legacyManifest.CreateElement('desktop7', 'Extension', $desktop7Ns)
    $shortcutExtension.SetAttribute('Category', 'windows.shortcut')
    $shortcut = $legacyManifest.CreateElement('desktop7', 'Shortcut', $desktop7Ns)
    $shortcut.SetAttribute('File', '[{Common Programs}]\BK-LMS Downloader.lnk')
    $shortcut.SetAttribute('Icon', '[{Package}]\Assets\BK-LMS-Downloader-icon-blue.ico')
    [void]$shortcutExtension.AppendChild($shortcut)
    [void]$extensions.AppendChild($shortcutExtension)
    [void]$legacyApp.AppendChild($extensions)
    $legacyManifest.Save((Join-Path $legacyPayload 'AppxManifest.xml'))

    $legacyPackage = Join-Path $legacyOutput "BK-LMS-Downloader_${legacyVersion}_x64.msix"
    & $makeAppx.FullName pack /d $legacyPayload /p $legacyPackage
    if ($LASTEXITCODE -ne 0) { throw "MakeAppx failed to pack the synthetic legacy package; exit code $LASTEXITCODE." }
    Sign-TestPackage -path $legacyPackage -signToolPath $signToolPath -thumbprint $testCertificateThumbprint

    Add-AppxPackage -Path $legacyPackage -ErrorAction Stop
    $legacyInstalled = Assert-InstalledPackage $legacyVersion
    $script:state.synthetic_legacy_install = 'PASS'
    $script:state.legacy_shortcut_manifest = 'PASS: desktop7 windows.shortcut extension with the specified Common Programs link'
    Start-Sleep -Seconds 4
    $legacyShortcuts = @(Get-BkShortcuts)
    foreach ($shortcutPath in $legacyShortcuts) {
        if ($shortcutPath -notin $baselineShortcuts) { [void]$createdShortcutPaths.Add($shortcutPath) }
    }
    $legacyShortcutPath = $legacyShortcuts |
        Where-Object { $_ -like (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\BK-LMS Downloader.lnk') } |
        Select-Object -First 1
    if ($legacyShortcutPath) {
        $script:state.legacy_shortcut_target = Get-ShortcutTarget $legacyShortcutPath
        if ($script:state.legacy_shortcut_target -match 'WindowsApps\\TiKyisme\.BK-LMSDownloader_1\.3\.0\.0_x64__') {
            $script:state.legacy_version_bound_shortcut = 'CONFIRMED'
        }
    }
    else {
        $script:state.legacy_shortcut_target = 'No matching .lnk appeared in the inspected user/common Start Menu or Desktop locations.'
    }

    $script:state.update_in_place = 'FAIL'
    Add-AppxPackage -Path $candidate -ErrorAction Stop
    $updated = Assert-InstalledPackage $candidateVersion
    $script:state.post_update_version = [string]$updated.Version
    $script:state.update_in_place = 'PASS'
    $postUpdateShortcut = Get-BkShortcuts |
        Where-Object { $_ -like (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\BK-LMS Downloader.lnk') } |
        Select-Object -First 1
    if ($postUpdateShortcut) {
        $postUpdateTarget = Get-ShortcutTarget $postUpdateShortcut
        if ($postUpdateTarget -match 'WindowsApps\\TiKyisme\.BK-LMSDownloader_1\.3\.0\.0_x64__' -and
            -not (Test-Path -LiteralPath $postUpdateTarget)) {
            $script:state.stale_shortcut_after_update = 'CONFIRMED: existing link still targets the removed 1.3.0.0 package path'
        }
        else {
            $script:state.stale_shortcut_after_update = "NOT_CONFIRMED: link remains but target is '$postUpdateTarget'"
        }
    }
    elseif ($script:state.legacy_shortcut_target -and
        $script:state.legacy_shortcut_target -ne 'No matching .lnk appeared in the inspected user/common Start Menu or Desktop locations.') {
        $script:state.stale_shortcut_after_update = 'NOT_CONFIRMED: legacy shortcut was removed during package update'
    }
    else {
        $script:state.stale_shortcut_after_update = 'NOT_CONFIRMED: synthetic legacy install created no shortcut to inspect'
    }

    $updatedStartApp = Get-StartAppMatch
    if (-not (Get-Command Get-StartApps -ErrorAction SilentlyContinue)) {
        $script:state.startapps_lookup = 'ENVIRONMENT_LIMITATION: Get-StartApps unavailable; package identity and manifest AUMID verified after update'
    }
    elseif (-not $updatedStartApp -or $updatedStartApp.AppID -ne $aumid) {
        $script:state.aumid_registration = 'FAIL after update'
        $script:state.startapps_lookup = 'FAIL after update: expected AUMID absent'
        throw 'Expected AUMID registration was not preserved after update-in-place.'
    }
    else {
        $script:state.startapps_lookup = 'PASS after update'
    }
    $script:state.post_update_aumid_launch = Test-AumidLaunch -installLocation $updated.InstallLocation -stage 'Post-update'

    if ($script:state.stale_shortcut_after_update -like 'CONFIRMED:*' -and $postUpdateShortcut -and
        $createdShortcutPaths.Contains($postUpdateShortcut)) {
        Remove-Item -LiteralPath $postUpdateShortcut -Force
        $afterRecoveryPackage = Assert-InstalledPackage $candidateVersion
        $afterRecoveryStartApp = Get-StartAppMatch
        if ($afterRecoveryPackage -and $afterRecoveryStartApp -and $afterRecoveryStartApp.AppID -eq $aumid) {
            $script:state.recovery_model = 'PASS: removed only the synthetic test link; package and AUMID registration remain'
        }
        else {
            $script:state.recovery_model = 'FAIL: package/AUMID registration changed after removing test link'
        }
    }
    else {
        $script:state.recovery_model = 'NOT APPLICABLE: no confirmed stale test-created link'
    }

    Remove-AppxPackage -Package $updated.PackageFullName -ErrorAction Stop
    if (Get-InstalledTargetPackage) { throw 'Could not remove the updated synthetic package before the fixed fresh-install check.' }
    foreach ($shortcutPath in @($createdShortcutPaths)) {
        if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
    }
    $createdShortcutPaths.Clear()

    Add-AppxPackage -Path $candidate -ErrorAction Stop
    $freshFixed = Assert-InstalledPackage $candidateVersion
    $freshStartApp = Get-StartAppMatch
    if ((Get-Command Get-StartApps -ErrorAction SilentlyContinue) -and
        (-not $freshStartApp -or $freshStartApp.AppID -ne $aumid)) {
        $script:state.aumid_registration = 'FAIL on fixed fresh install'
        $script:state.startapps_lookup = 'FAIL on fixed fresh install: expected AUMID absent'
        throw 'AUMID registration was missing on the final fixed-package fresh install.'
    }
    elseif (-not (Get-Command Get-StartApps -ErrorAction SilentlyContinue)) {
        $script:state.startapps_lookup = 'ENVIRONMENT_LIMITATION: Get-StartApps unavailable; package identity and manifest AUMID verified'
        $script:state.aumid_registration = 'PASS (package identity and manifest Application Id)'
    }
    else {
        $script:state.startapps_lookup = 'PASS on fixed fresh install'
        $script:state.aumid_registration = 'PASS'
    }
    $fixedShortcuts = @(Get-BkShortcuts)
    $newFixedShortcuts = @($fixedShortcuts | Where-Object { $_ -notin $baselineShortcuts })
    if ($newFixedShortcuts.Count -eq 0) {
        $script:state.fixed_fresh_install_shortcut = 'PASS: no package-created BK-LMS Downloader .lnk appeared'
    }
    else {
        $script:state.fixed_fresh_install_shortcut = "FAIL: unexpected shortcut(s): $($newFixedShortcuts -join ', ')"
        throw $script:state.fixed_fresh_install_shortcut
    }

    if ($appCertPath) {
        $sessionId = (Get-Process -Id $PID).SessionId
        if ($sessionId -eq 0) {
            $script:state.wack = 'NOT RUN: hosted runner is in Session 0; WACK requires an active user session'
        }
        else {
            $reportPath = Join-Path $testRoot 'wack-report.xml'
            & $appCertPath reset
            if ($LASTEXITCODE -ne 0) { throw "WACK reset failed with exit code $LASTEXITCODE." }
            & $appCertPath test -appxpackagepath $candidate -reportoutputpath $reportPath
            if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $reportPath)) {
                $script:state.wack = 'PASS'
            }
            else {
                $script:state.wack = "FAIL: appcert exit code $LASTEXITCODE; report exists: $(Test-Path -LiteralPath $reportPath)"
                throw $script:state.wack
            }
        }
    }
    else {
        $script:state.wack = 'NOT RUN: App Certification Kit is not installed on the hosted runner'
    }
}
catch {
    $script:state.failure = $_.Exception.Message
}
finally {
    try {
        foreach ($processId in @($script:testProcessIds)) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            if ($process -and $process.ExecutablePath -and
                $process.ExecutablePath -like '*WindowsApps*' -and
                $process.ExecutablePath -like "*${identityName}_*") {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
        if ($script:ownedTestPackageLifecycle) {
            foreach ($package in @(Get-AppxPackage -Name $identityName -ErrorAction SilentlyContinue)) {
                Remove-AppxPackage -Package $package.PackageFullName -ErrorAction SilentlyContinue
            }
        }
        foreach ($shortcutPath in @($createdShortcutPaths)) {
            if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue }
        }
        if ($testCertificateThumbprint) {
            Remove-Item -LiteralPath "Cert:\LocalMachine\TrustedPeople\$testCertificateThumbprint" -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath "Cert:\LocalMachine\My\$testCertificateThumbprint" -Force -ErrorAction SilentlyContinue
        }
        $publicCertPath = Join-Path $testRoot 'ephemeral-test-publisher.cer'
        if (Test-Path -LiteralPath $publicCertPath) { Remove-Item -LiteralPath $publicCertPath -Force -ErrorAction SilentlyContinue }
        $script:state.cleanup = 'PASS: test package registrations, created shortcut(s), and ephemeral certificate removed'
    }
    catch {
        $script:state.cleanup = "WARN: cleanup encountered $($_.Exception.Message)"
        if (-not $script:state.failure) { $script:state.failure = $script:state.cleanup }
    }
    Write-RunSummary
}

if ($script:state.failure) {
    Write-Host "::error::$($script:state.failure)"
    exit 1
}
