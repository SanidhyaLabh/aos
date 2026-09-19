@echo off
TITLE Origin // ASO v3.1 Bounded-Loss Architecture
echo ====================================================================
echo   ORIGIN // ASO v3.1 — Manipulation-Cost-Aware Oracle & Bounded-Loss
echo ====================================================================
echo.

echo [1/4] Checking Node.js and Python dependencies...
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

echo [2/4] Installing Python requirements if needed...
python -m pip install flask flask-cors --quiet

echo [3/4] Starting Python Risk Engine Backend (Port 5001)...
start "Origin // Python Risk Engine (Port 5001)" cmd /k "python backend/terminal_backend.py"

timeout /t 2 /nobreak >nul

echo [4/4] Starting Frontend Terminal (Port 5173)...
start "Origin // Vite Frontend (Port 5173)" cmd /k "npm run dev"

timeout /t 3 /nobreak >nul

echo.
echo ====================================================================
echo   System running!
echo   - Terminal URL: http://localhost:5173/terminal
echo   - Landing Page: http://localhost:5173/
echo   - Python Backend: http://localhost:5001/status
echo ====================================================================
echo Opening http://localhost:5173/terminal in your default browser...
start http://localhost:5173/terminal

echo.
echo Press any key to exit this launcher window (services will stay running in their windows)...
pause >nul
