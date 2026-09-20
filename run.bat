@echo off
TITLE ORIGIN // Economic Exposure Guard (EEG)
echo ====================================================================
echo   ORIGIN // ECONOMIC EXPOSURE GUARD (EEG) -- HACKATHON LAUNCHER
echo   Bounded-Loss Debt Velocity Limiter and On-Chain Risk Engine
echo ====================================================================
echo.

:: Add Foundry / Anvil to PATH if present
if exist "%USERPROFILE%\.foundry\bin" (
    set "PATH=%USERPROFILE%\.foundry\bin;%PATH%"
)

echo [1/5] Checking Node.js and Python...
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed or not in PATH. Please install Node.js 18+.
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.9+.
    pause
    exit /b 1
)

echo [2/5] Verifying Python backend dependencies (flask, flask-cors)...
python -m pip install flask flask-cors --quiet

echo [3/5] Checking local EVM node (Anvil on port 8545)...
netstat -ano | findstr :8545 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo   -^> Starting Anvil EVM node on port 8545...
    if exist "%USERPROFILE%\.foundry\bin\anvil.exe" (
        start "Origin // Anvil EVM (Port 8545)" cmd /k ""%USERPROFILE%\.foundry\bin\anvil.exe" --port 8545 --chain-id 31337"
    ) else (
        start "Origin // Anvil EVM (Port 8545)" cmd /k "anvil --port 8545 --chain-id 31337"
    )
    timeout /t 3 /nobreak >nul
) else (
    echo   -^> Anvil already active on port 8545.
)

echo [4/5] Deploying and verifying contracts on EVM...
call node scripts/deploy.js
if errorlevel 1 (
    echo [WARNING] Contract deployment failed. Continuing with existing deployment...
)

echo [5/5] Checking and starting background services...

:: Python Risk Engine and EEG Backend (port 5001)
netstat -ano | findstr :5001 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo   -^> Starting Python Backend on port 5001...
    start "Origin // Python EEG Backend (Port 5001)" cmd /k "python backend/terminal_backend.py"
    timeout /t 2 /nobreak >nul
) else (
    echo   -^> Python backend already active on port 5001.
)

:: Vite Frontend (port 5173)
netstat -ano | findstr :5173 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo   -^> Starting Vite Dev Server on port 5173...
    start "Origin // Vite Frontend (Port 5173)" cmd /k "npm run dev"
    timeout /t 2 /nobreak >nul
) else (
    echo   -^> Vite dev server already active on port 5173.
)

echo.
echo ====================================================================
echo   ORIGIN EEG SYSTEM ONLINE!
echo   ------------------------------------------------------------------
echo   Terminal UI:    http://localhost:5173/terminal
echo   Overview Page:  http://localhost:5173/
echo   EEG State API:  http://localhost:5001/api/eeg/state
echo   Local EVM RPC:  http://127.0.0.1:8545
echo ====================================================================
echo.
echo Launching http://localhost:5173/terminal in default browser...
start http://localhost:5173/terminal

echo.
echo [2-MINUTE JUDGE DEMO FLOW IN TERMINAL]:
echo   1. Click '1. Normal ($2.9k)'    -^> Honest borrow succeeds in 1 tx
echo   2. Click '2. $10M Exploit'      -^> Blocked on-chain by EEG (REVERT)
echo   3. Click '3. Sybil (4 Wallets)' -^> Shared bucket defeats multi-wallet split
echo   4. Click '4. Refill (+15m)'     -^> Advances time, linearly refilling +$25k
echo   5. Click '5. Repay'             -^> Ungated repayment; no artificial refill
echo.
echo Press any key to close this launcher window (services will stay running)...
pause >nul
