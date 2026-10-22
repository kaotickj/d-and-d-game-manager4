$ErrorActionPreference = "Stop"
$acceptanceRoot = Join-Path $PWD "dist/windows-acceptance"
New-Item -ItemType Directory -Force -Path $acceptanceRoot | Out-Null
$reportDirectory = Join-Path $acceptanceRoot ("run-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $reportDirectory | Out-Null

function Invoke-DesktopSmoke([string]$Executable, [string]$Report) {
    $process = Start-Process -FilePath $Executable -ArgumentList "--smoke-test `"$Report`"" -PassThru
    if (!$process.WaitForExit(120000)) {
        $process.Kill()
        throw "Packaged application acceptance timed out: $Executable"
    }
    if ($process.ExitCode -ne 0) { throw "Packaged application exited with $($process.ExitCode): $Executable" }
    if (!(Test-Path $Report)) { throw "Packaged application did not create its acceptance report" }
    $result = Get-Content $Report -Raw | ConvertFrom-Json
    if ($result.status -ne "passed") { throw "Packaged application acceptance failed: $Report" }
    if ($result.frozen -ne $true -or $result.platform -notlike "Windows*") {
        throw "Acceptance report did not come from a frozen Windows application"
    }
    Write-Output (Get-Content $Report -Raw)
}

Invoke-DesktopSmoke (Join-Path $PWD "dist/DnDGameManager4/DnDGameManager4.exe") (Join-Path $reportDirectory "bundled.json")

$installDirectory = Join-Path $env:RUNNER_TEMP "DnDGameManager4-acceptance"
$installer = Join-Path $PWD "dist/DnDGameManager4-Setup.exe"
$profileRoot = Join-Path $reportDirectory "retained-profile"
$fixtureReport = Join-Path $reportDirectory "retained-library.json"
python ./build/windows_upgrade_fixture.py seed $profileRoot $fixtureReport
if ($LASTEXITCODE -ne 0) { throw "Could not prepare the isolated upgrade fixture" }
$acceptanceOriginalLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $profileRoot
    foreach ($pass in @("installed", "reinstalled")) {
        $log = Join-Path $reportDirectory "$pass-setup.log"
        $arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$installDirectory`" /LOG=`"$log`""
        $setup = Start-Process -FilePath $installer -ArgumentList $arguments -PassThru
        if (!$setup.WaitForExit(120000)) {
            $setup.Kill()
            throw "Silent installation timed out"
        }
        if ($setup.ExitCode -ne 0) { throw "Silent installation failed with $($setup.ExitCode)" }
        python ./build/windows_upgrade_fixture.py check $profileRoot $fixtureReport | Tee-Object -FilePath (Join-Path $reportDirectory "$pass-data-preservation.json")
        if ($LASTEXITCODE -ne 0) { throw "Installation changed existing campaign data" }
        Invoke-DesktopSmoke (Join-Path $installDirectory "DnDGameManager4.exe") (Join-Path $reportDirectory "$pass.json")
        python ./build/windows_upgrade_fixture.py check $profileRoot $fixtureReport
        if ($LASTEXITCODE -ne 0) { throw "Packaged acceptance touched the isolated default library" }
    }
} finally {
    $env:LOCALAPPDATA = $acceptanceOriginalLocalAppData
}
