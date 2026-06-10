# 30-minute smoke test — validates an engine change against two reference
# questions: gen-evbattery (known-good general case, baseline 8.0/10) and
# sci-aspirin (formerly-fatal scientific case: read-gate + 403-mirror path).
# Caps: 15 min / $1 / 4 cycles per question => ~30 min, ~$2 worst case total.
#
# Usage (from repo root):
#   powershell -File scripts\smoke_test.ps1                # both questions
#   powershell -File scripts\smoke_test.ps1 -SciOnly       # the hard one only
#   powershell -File scripts\smoke_test.ps1 -Tag readgate2 # label the results
#
# Results land in evals\results\smoke-<tag>-{sci,gen}\scores.json; compare
# mean/finish/$ against the reference legs in evals\results\baseline*.
param(
    [string]$Tag = (Get-Date -Format 'MMdd-HHmm'),
    [switch]$SciOnly,
    [switch]$GenOnly
)
$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8 = '1'
$B = '.venv\Scripts\python.exe'
$caps = @('--max-wall-hours', '0.25', '--max-budget-usd', '1.0', '--max-cycles', '4')

$legs = @()
if (-not $GenOnly) { $legs += @{ n = "smoke-$Tag-sci"; a = @('--only', 'sci-aspirin') } }
if (-not $SciOnly) { $legs += @{ n = "smoke-$Tag-gen"; a = @('--only', 'gen-evbattery') } }

foreach ($l in $legs) {
    $out = "evals/results/$($l.n)"
    Write-Host "=== smoke leg $($l.n) ===" -ForegroundColor Cyan
    & $B evals/run_evals.py @caps --out $out @($l.a) 2>&1 |
        Tee-Object -FilePath "runs\$($l.n).log"
}

Write-Host "`n=== smoke summary ===" -ForegroundColor Cyan
foreach ($l in $legs) {
    $sj = "evals/results/$($l.n)/scores.json"
    if (Test-Path $sj) {
        $r = Get-Content $sj -Encoding UTF8 | ConvertFrom-Json
        Write-Host ("{0}: scored {1}/{2}, mean={3}, spend=`${4}" -f $l.n,
            $r.n_scored, $r.n_questions, $r.mean_overall, $r.total_spend_usd)
    } else {
        Write-Host "$($l.n): NO scores.json (leg crashed or hung - check runs\$($l.n).log)" -ForegroundColor Red
    }
}
