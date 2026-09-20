@echo off
TITLE ORIGIN // Economic Exposure Guard (EEG)
echo ====================================================================
echo   ORIGIN // ECONOMIC EXPOSURE GUARD (EEG) — HACKATHON LAUNCHER
echo   Bounded-Loss Debt Velocity Limiter & On-Chain Risk Engine
echo ====================================================================
echo.

:: Add Foundry / Anvil to PATH if present in user profile
set "PATH=%USERPROFILE%\.foundry\bin;%PATH%"

echo [1/6] Checking system prerequisites (Node.js, Python, Foundry)...
where node >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH. Please install Node.js 18+.
    pause
    exit /b 1
)

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.9+.
    pause
    exit /b 1
)

echo [2/6] Verifying Python backend dependencies (flask, flask-cors)...
python -m pip install flask flask-cors --quiet

echo [3/6] Checking local EVM node (Anvil on port 8545)...
powershell -Command "if (!(Get-NetTCPConnection -LocalPort 8545 -ErrorAction SilentlyContinue)) { exit 1 }" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo   -> Starting Anvil on port 8545 (Chain ID 31337)...
    if exist "%USERPROFILE%\.foundry\bin\anvil.exe" (
        start "Origin // Anvil EVM (Port 8545)" cmd /k ""%USERPROFILE%\.foundry\bin\anvil.exe" --port 8545 --chain-id 31337"
    ) else (
        start "Origin // Anvil EVM (Port 8545)" cmd /k "anvil --port 8545 --chain-id 31337"
    )
    timeout /t 3 /nobreak >nul
) else (
    echo   -> Anvil already active on port 8545.
)

echo [4/6] Deploying / verifying smart contracts on local EVM...
node scripts/deploy.js
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Contract deployment returned error. Continuing with existing deployment...
)

echo [5/6] Starting background services...

:: Mock sources server on port 4000
powershell -Command "if (!(Get-NetTCPConnection -LocalPort 4000 -ErrorAction SilentlyContinue)) { exit 1 }" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    start "Origin // Mock Sources Server (Port 4000)" cmd /k "node service/mockSourcesServer.js"
)

:: Python Risk Engine & EEG Backend on port 5001
powershell -Command "if (!(Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue)) { exit 1 }" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    start "Origin // Python EEG Backend (Port 5001)" cmd /k "python backend/terminal_backend.py"
) else (
    echo   -> Python backend already active on port 5001.
)

:: Vite Frontend on port 5173
powershell -Command "if (!(Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue)) { exit 1 }" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    start "Origin // Vite Frontend (Port 5173)" cmd /k "npm run dev"
) else (
    echo   -> Vite dev server already active on port 5173.
)

timeout /t 3 /nobreak >nul

echo.
echo ====================================================================
echo   ORIGIN EEG SYSTEM ONLINE!
echo   ------------------------------------------------------------------
echo   • Terminal Dashboard: http://localhost:5173/terminal
echo   • Overview / Landing: http://localhost:5173/
echo   • EEG API State:      http://localhost:5001/api/eeg/state
echo   • Local Anvil RPC:    http://127.0.0.1:8545
echo ====================================================================
echo.
echo Launching http://localhost:5173/terminal in default browser...
start http://localhost:5173/terminal

echo.
echo [2-MINUTE JUDGE DEMO STEPS IN TERMINAL]:
echo   1. Click '1. Normal ($2.9k)'   -> Honest borrow succeeds in 1 tx
echo   2. Click '2. $10M Exploit'     -> Blocked on-chain by EEG (REVERT)
echo   3. Click '3. Sybil (4 Wallets)'-> Shared bucket defeats multi-wallet split
echo   4. Click '4. Refill (+15m)'    -> Advances time, linearly refilling +$25k
echo   5. Click '5. Repay'            -> Ungated repayment; no artificial refill
echo.
echo Services will remain running in their respective windows.
echo Press any key to exit this launcher window...
pause >nul
