#!/bin/bash

# arXiv Summarizer Setup Script
# This script helps you set up the arXiv Summarizer with authentication features

echo "🚀 Setting up arXiv Summarizer with Authentication Features"
echo "=========================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check if Python is installed
print_step "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3.8 or above."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
print_status "Found Python $PYTHON_VERSION"

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    print_error "pip3 is not installed. Please install pip3."
    exit 1
fi

# Create virtual environment
print_step "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_status "Virtual environment created"
else
    print_warning "Virtual environment already exists"
fi

# Activate virtual environment
print_step "Activating virtual environment..."
source venv/bin/activate
print_status "Virtual environment activated"

# Install dependencies
print_step "Installing Python dependencies..."
pip install -r requirements.txt
if [ $? -eq 0 ]; then
    print_status "Dependencies installed successfully"
else
    print_error "Failed to install dependencies"
    exit 1
fi

# Set up environment file
print_step "Setting up environment configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    print_status "Environment file created from template"
    print_warning "Please edit .env file with your API keys and OAuth credentials"
else
    print_warning ".env file already exists"
fi

# Create necessary directories
print_step "Creating necessary directories..."
mkdir -p uploads
mkdir -p flask_session
print_status "Directories created"

# Database initialization
print_step "Initializing database..."
python3 -c "
from db import Base, engine
Base.metadata.create_all(engine)
print('Database initialized successfully')
"

print_status "Database tables created"

echo ""
echo "✅ Setup Complete!"
echo "=================="
echo ""
echo "📋 Next Steps:"
echo "1. Edit the .env file with your API keys:"
echo "   - GEMINI_API_KEY (required for summarization)"
echo "   - GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (optional, for Google sign-in)"
echo ""
echo "2. To run the application:"
echo "   source venv/bin/activate  # Activate virtual environment"
echo "   python app.py             # Start the application"
echo ""
echo "3. Open your browser and go to: http://localhost:5000"
echo ""
echo "📚 For OAuth setup instructions, see README.md"
echo ""
echo "🔐 Authentication Features:"
echo "   - Google OAuth sign-in"
echo "   - Personal summary history"
echo "   - Cross-device synchronization"
echo ""
echo "Need help? Check out the documentation or create an issue on GitHub!"
