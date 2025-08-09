@echo off
REM arXiv Summarizer Setup Script for Windows
REM This script helps you set up the arXiv Summarizer with authentication features

echo 🚀 Setting up arXiv Summarizer with Authentication Features
echo ==========================================================

REM Check if Python is installed
echo [STEP] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed. Please install Python 3.8 or above.
    exit /b 1
)
echo [INFO] Python is installed

REM Check if pip is installed
echo [STEP] Checking pip installation...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] pip is not installed. Please install pip.
    exit /b 1
)
echo [INFO] pip is installed

REM Create virtual environment
echo [STEP] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    echo [INFO] Virtual environment created
) else (
    echo [WARNING] Virtual environment already exists
)

REM Activate virtual environment
echo [STEP] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo [STEP] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)
echo [INFO] Dependencies installed successfully

REM Set up environment file
echo [STEP] Setting up environment configuration...
if not exist ".env" (
    copy .env.example .env
    echo [INFO] Environment file created from template
    echo [WARNING] Please edit .env file with your API keys and OAuth credentials
) else (
    echo [WARNING] .env file already exists
)

REM Create necessary directories
echo [STEP] Creating necessary directories...
if not exist "uploads" mkdir uploads
if not exist "flask_session" mkdir flask_session
echo [INFO] Directories created

REM Database initialization
echo [STEP] Initializing database...
python -c "from db import Base, engine; Base.metadata.create_all(engine); print('Database initialized successfully')"
echo [INFO] Database tables created

echo.
echo ✅ Setup Complete!
echo ==================
echo.
echo 📋 Next Steps:
echo 1. Edit the .env file with your API keys:
echo    - GEMINI_API_KEY (required for summarization)
echo    - GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (optional, for Google sign-in)
echo.
echo 2. To run the application:
echo    venv\Scripts\activate.bat  # Activate virtual environment
echo    python app.py              # Start the application
echo.
echo 3. Open your browser and go to: http://localhost:5000
echo.
echo 📚 For OAuth setup instructions, see README.md
echo.
echo 🔐 Authentication Features:
echo    - Google OAuth sign-in
echo    - Personal summary history
echo    - Cross-device synchronization
echo.
echo Need help? Check out the documentation or create an issue on GitHub!

pause
