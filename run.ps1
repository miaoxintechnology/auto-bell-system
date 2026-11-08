param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$argsList = @()
if ($NoBrowser) { $argsList += "--no-browser" }
python run.py @argsList
