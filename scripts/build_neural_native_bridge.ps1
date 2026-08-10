param(
    [Parameter(Mandatory = $true)]
    [string]$LlamaSourceRoot,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = Split-Path -Parent $PSScriptRoot
$ContractPath = Join-Path $Repo "native\neural_bridge\bridge_contract.json"
$BridgeSource = Join-Path $Repo "native\neural_bridge\luna_nr2b_shim_harmony.cpp"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Read-ExportNames {
    param([Parameter(Mandatory = $true)][string]$DumpPath)

    $Names = New-Object System.Collections.Generic.List[string]
    foreach ($Line in (Get-Content -LiteralPath $DumpPath -Encoding utf8)) {
        $Match = [regex]::Match(
            $Line,
            '^\s+\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+([^\s=]+)'
        )
        if ($Match.Success) {
            $Name = $Match.Groups[1].Value
            if ($Name -match '^[A-Za-z_?@]' -and -not $Names.Contains($Name)) {
                $Names.Add($Name)
            }
        }
    }
    return @($Names)
}

function Write-DefFile {
    param(
        [Parameter(Mandatory = $true)][string]$DumpPath,
        [Parameter(Mandatory = $true)][string]$LibraryName,
        [Parameter(Mandatory = $true)][string]$DefPath
    )

    $Names = @(Read-ExportNames -DumpPath $DumpPath)
    if ($Names.Count -eq 0) {
        throw "No exports parsed from $DumpPath"
    }

    $Out = New-Object System.Collections.Generic.List[string]
    $Out.Add("LIBRARY $LibraryName")
    $Out.Add("EXPORTS")
    foreach ($Name in $Names) {
        $Out.Add("    $Name")
    }

    [System.IO.File]::WriteAllLines(
        $DefPath,
        $Out,
        [System.Text.ASCIIEncoding]::new()
    )
}

if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) {
    throw "Bridge contract missing."
}
if (-not (Test-Path -LiteralPath $BridgeSource -PathType Leaf)) {
    throw "Bridge source missing."
}

$Contract = Get-Content -LiteralPath $ContractPath -Encoding utf8 | ConvertFrom-Json

if ($Contract.schema_version -ne 1) {
    throw "Unsupported bridge contract schema."
}
if ((Get-Sha256 -Path $BridgeSource) -ne $Contract.bridge_source_sha256) {
    throw "Bridge source hash does not match contract."
}

$LlamaHead = ((& git -C $LlamaSourceRoot rev-parse HEAD 2>$null) -join "").Trim()
$LlamaTag = ((& git -C $LlamaSourceRoot describe --tags --exact-match HEAD 2>$null) -join "").Trim()
$LlamaRemote = ((& git -C $LlamaSourceRoot remote get-url origin 2>$null) -join "").Trim()
$LlamaStatus = @(& git -C $LlamaSourceRoot status --porcelain=v1)

if ($LlamaHead -ne $Contract.llama_cpp.commit) {
    throw "llama.cpp commit mismatch."
}
if ($LlamaTag -ne $Contract.llama_cpp.tag) {
    throw "llama.cpp tag mismatch."
}
if ($LlamaRemote -ne $Contract.llama_cpp.repository) {
    throw "llama.cpp remote mismatch."
}
if ($LlamaStatus.Count -ne 0) {
    throw "llama.cpp checkout must be clean."
}

foreach ($Property in $Contract.llama_cpp.locked_files.PSObject.Properties) {
    $Relative = $Property.Name.Replace("/", "\")
    $Path = Join-Path $LlamaSourceRoot $Relative
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Pinned llama.cpp file missing: $($Property.Name)"
    }
    if ((Get-Sha256 -Path $Path) -ne $Property.Value) {
        throw "Pinned llama.cpp file hash mismatch: $($Property.Name)"
    }
}

foreach ($Property in $Contract.runtime_assets.locked_files.PSObject.Properties) {
    $Path = Join-Path $RuntimeDir $Property.Name
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Pinned runtime DLL missing: $($Property.Name)"
    }
    if ((Get-Sha256 -Path $Path) -ne $Property.Value) {
        throw "Pinned runtime DLL hash mismatch: $($Property.Name)"
    }
}

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $VsWhere -PathType Leaf)) {
    throw "vswhere.exe not found."
}

$VsInstall = (
    & $VsWhere `
        -latest `
        -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
) -join ""

$VsInstall = $VsInstall.Trim()
if (-not $VsInstall) {
    throw "Visual Studio C++ Build Tools not found."
}

$VsDevCmd = Join-Path $VsInstall "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path -LiteralPath $VsDevCmd -PathType Leaf)) {
    throw "VsDevCmd.bat not found."
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$RepoFull = [System.IO.Path]::GetFullPath($Repo)
$RepoNormalized = $RepoFull.TrimEnd("\", "/")
$OutputNormalized = $OutputDir.TrimEnd("\", "/")
$RepoPrefix = $RepoNormalized + [System.IO.Path]::DirectorySeparatorChar

if (
    $OutputNormalized.Equals(
        $RepoNormalized,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or
    $OutputNormalized.StartsWith(
        $RepoPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "OutputDir must be outside the Luna repository."
}

if (Test-Path -LiteralPath $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}

$ExportDir = Join-Path $OutputDir "exports"
$ImportDir = Join-Path $OutputDir "import"
$BuildDir = Join-Path $OutputDir "build"
New-Item -ItemType Directory -Path $ExportDir -Force | Out-Null
New-Item -ItemType Directory -Path $ImportDir -Force | Out-Null
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

$DllMap = [ordered]@{
    "llama" = Join-Path $RuntimeDir "llama.dll"
    "ggml" = Join-Path $RuntimeDir "ggml.dll"
    "ggml-base" = Join-Path $RuntimeDir "ggml-base.dll"
}

$DumpCmd = Join-Path $OutputDir "dump.cmd"
$DumpLines = New-Object System.Collections.Generic.List[string]
$DumpLines.Add("@echo off")
$DumpLines.Add("setlocal")
$DumpLines.Add("call `"$VsDevCmd`" -no_logo -arch=x64 -host_arch=x64")
$DumpLines.Add("if errorlevel 1 exit /b 20")

$ExitCode = 21
foreach ($Entry in $DllMap.GetEnumerator()) {
    $DumpPath = Join-Path $ExportDir "$($Entry.Key).txt"
    $DumpLines.Add("dumpbin.exe /nologo /exports `"$($Entry.Value)`" > `"$DumpPath`"")
    $DumpLines.Add("if errorlevel 1 exit /b $ExitCode")
    $ExitCode++
}
$DumpLines.Add("exit /b 0")

[System.IO.File]::WriteAllLines(
    $DumpCmd,
    $DumpLines,
    [System.Text.ASCIIEncoding]::new()
)

& cmd.exe /d /c "`"$DumpCmd`""
if ($LASTEXITCODE -ne 0) {
    throw "DLL export extraction failed."
}

foreach ($Entry in $DllMap.GetEnumerator()) {
    Write-DefFile `
        -DumpPath (Join-Path $ExportDir "$($Entry.Key).txt") `
        -LibraryName $Entry.Key `
        -DefPath (Join-Path $ImportDir "$($Entry.Key).def")
}

$ObjectPath = Join-Path $BuildDir "luna_nr2b_shim_harmony.obj"
$BridgeDll = Join-Path $BuildDir "luna_neural_bridge.dll"
$BridgeLib = Join-Path $BuildDir "luna_neural_bridge.lib"
$BuildLog = Join-Path $OutputDir "build.log"
$BuildCmd = Join-Path $OutputDir "build.cmd"
$IncludeLlama = Join-Path $LlamaSourceRoot "include"
$IncludeGgml = Join-Path $LlamaSourceRoot "ggml\include"

$BuildLines = @(
    "@echo off",
    "setlocal",
    "call `"$VsDevCmd`" -no_logo -arch=x64 -host_arch=x64",
    "if errorlevel 1 exit /b 30",
    "lib.exe /nologo /machine:x64 /def:`"$ImportDir\llama.def`" /out:`"$ImportDir\llama.lib`"",
    "if errorlevel 1 exit /b 31",
    "lib.exe /nologo /machine:x64 /def:`"$ImportDir\ggml.def`" /out:`"$ImportDir\ggml.lib`"",
    "if errorlevel 1 exit /b 32",
    "lib.exe /nologo /machine:x64 /def:`"$ImportDir\ggml-base.def`" /out:`"$ImportDir\ggml-base.lib`"",
    "if errorlevel 1 exit /b 33",
    "pushd `"$BuildDir`"",
    "if errorlevel 1 exit /b 34",
    "cl.exe /nologo /std:c++17 /EHsc /O2 /LD /Brepro /Fo`"$ObjectPath`" /I`"$IncludeLlama`" /I`"$IncludeGgml`" `"$BridgeSource`" /link /Brepro /OUT:`"$BridgeDll`" /IMPLIB:`"$BridgeLib`" /LIBPATH:`"$ImportDir`" llama.lib ggml.lib ggml-base.lib",
    "if errorlevel 1 exit /b 35",
    "popd",
    "dumpbin.exe /nologo /exports `"$BridgeDll`" > `"$ExportDir\bridge.txt`"",
    "if errorlevel 1 exit /b 36",
    "exit /b 0"
)

[System.IO.File]::WriteAllLines(
    $BuildCmd,
    $BuildLines,
    [System.Text.ASCIIEncoding]::new()
)

& cmd.exe /d /c "`"$BuildCmd`" > `"$BuildLog`" 2>&1"
if ($LASTEXITCODE -ne 0) {
    Get-Content -LiteralPath $BuildLog
    throw "Native bridge build failed."
}

$BridgeExports = @(
    Read-ExportNames -DumpPath (Join-Path $ExportDir "bridge.txt") |
        Where-Object { $_ -like "luna_nr2b_*" }
)

$RequiredExports = @($Contract.required_exports)
foreach ($Name in $RequiredExports) {
    if ($BridgeExports -notcontains $Name) {
        throw "Required ABI export missing: $Name"
    }
}

$UnexpectedExports = @(
    $BridgeExports |
        Where-Object { $RequiredExports -notcontains $_ }
)
if ($UnexpectedExports.Count -gt 0) {
    throw "Unexpected Luna ABI export(s): $($UnexpectedExports -join ', ')"
}

$Receipt = [ordered]@{
    schema_version = 1
    status = "PASS_REPO_OWNED_NATIVE_BRIDGE_BUILD"
    bridge_source_sha256 = Get-Sha256 -Path $BridgeSource
    bridge_binary = $BridgeDll
    bridge_binary_sha256 = Get-Sha256 -Path $BridgeDll
    bridge_binary_size_bytes = (Get-Item -LiteralPath $BridgeDll).Length
    abi_version = $Contract.abi_version
    abi_exports = $BridgeExports
    llama_cpp_commit = $LlamaHead
    llama_cpp_tag = $LlamaTag
    llama_cpp_repository = $LlamaRemote
    runtime_dir = [System.IO.Path]::GetFullPath($RuntimeDir)
    output_dir = $OutputDir
    repo_mutation = $false
    model_load = $false
    inference = $false
}

[System.IO.File]::WriteAllText(
    (Join-Path $OutputDir "build_receipt.json"),
    ($Receipt | ConvertTo-Json -Depth 10) + "`n",
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "status: PASS_REPO_OWNED_NATIVE_BRIDGE_BUILD"
Write-Host "bridge_binary: $BridgeDll"
Write-Host "bridge_sha256: $($Receipt.bridge_binary_sha256)"
Write-Host "receipt: $(Join-Path $OutputDir 'build_receipt.json')"
