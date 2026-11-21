# Ansai watchdog: keep office (:8080) and cloudflared alive. Run every 5 min by AnsaiWatchdog task.
$ErrorActionPreference = 'SilentlyContinue'
$log = 'C:\ansai-substrate\deploy\windows-persist\watchdog.log'
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $log -Append -Encoding ascii }

try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/health' -UseBasicParsing -TimeoutSec 8
    if ($r.StatusCode -ne 200) { Log "office health HTTP $($r.StatusCode) - starting AnsaiOffice"; Start-ScheduledTask -TaskName 'AnsaiOffice' }
} catch {
    Log "office health FAILED ($($_.Exception.Message)) - starting AnsaiOffice"
    Start-ScheduledTask -TaskName 'AnsaiOffice'
}

$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Log 'cloudflared process missing - starting AnsaiCloudflared'
    Start-ScheduledTask -TaskName 'AnsaiCloudflared'
}

try {
    $r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:8091/api/health' -UseBasicParsing -TimeoutSec 8
    if ($r2.StatusCode -ne 200) { Log "frontier health HTTP $($r2.StatusCode) - starting AnsaiFrontier"; Start-ScheduledTask -TaskName 'AnsaiFrontier' }
} catch {
    Log "frontier health FAILED ($($_.Exception.Message)) - starting AnsaiFrontier"
    Start-ScheduledTask -TaskName 'AnsaiFrontier'
}
