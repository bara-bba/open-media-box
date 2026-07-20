# Copy the Linux tester to the Pi and run it over SSH — the "real" test.
#
# Usage:
#   .\run_on_pi.ps1 -PiHost pi@raspberrypi.local
#   .\run_on_pi.ps1 -PiHost pi@192.168.1.42
#
# Requires the OpenSSH client (built into Windows 10/11) and the Pi reachable
# on the network with SSH enabled.

param(
    [Parameter(Mandatory = $true)]
    [string]$PiHost
)

$ErrorActionPreference = "Stop"
$local = Join-Path $PSScriptRoot "remote_test.py"

Write-Host "Copying remote_test.py to $PiHost ..."
scp $local "${PiHost}:~/remote_test.py"

Write-Host "Ensuring python3-evdev is installed on the Pi ..."
ssh $PiHost "sudo apt-get install -y python3-evdev"

Write-Host "Running the tester on the Pi (Ctrl+C to stop) ..."
ssh -t $PiHost "sudo python3 ~/remote_test.py"
