# Moves the database from Kamni's schema branch to Richa's, preserving user accounts.
#
# A full backup of the current (Kamni) database was taken to the scratchpad first:
#   ...\scratchpad\binance_db_backup_kamni_schema.sql
# so nothing is unrecoverable. This script drops Kamni's test trading tables (orders,
# trades, accounts, ledger) but KEEPS the users table and every account in it.
#
# Run from the server folder:  cd "d:\setupfx code\Binance_exchange-\server"; .\migrate_to_richa.ps1

$ErrorActionPreference = "Stop"
$alembic = ".\.venv\Scripts\alembic.exe"
$py      = ".\.venv\Scripts\python.exe"

Write-Host "== 1/4 downgrade Kamni's chain to the shared users-table base ==" -ForegroundColor Cyan
& $alembic downgrade d2893adb5ae2
if (-not $?) { throw "downgrade failed" }

Write-Host "== 2/4 remove Kamni's superseded migration files (leaves Richa's as the single head) ==" -ForegroundColor Cyan
Remove-Item -Force alembic\versions\28837cae7296_*.py,
                   alembic\versions\81dca55a1579_*.py,
                   alembic\versions\d2310868c178_*.py,
                   alembic\versions\0c6bb817d209_*.py

Write-Host "== 3/4 apply Richa's chain ==" -ForegroundColor Cyan
& $alembic upgrade head
if (-not $?) { throw "upgrade failed" }

Write-Host "== 4/4 seed assets + markets ==" -ForegroundColor Cyan
& $py -m app.seed

Write-Host "`nDone. Schema is now Richa's; user accounts preserved." -ForegroundColor Green
& $alembic current
