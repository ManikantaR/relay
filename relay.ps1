# relay.ps1 — entrypoint (Windows). Dispatches to the Python control plane.
param([Parameter(ValueFromRemainingArguments)] $Args)
Set-Location $PSScriptRoot
& python py\relay_cli.py @Args
