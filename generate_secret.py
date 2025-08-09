#!/usr/bin/env python3
"""
Quick setup helper for arXiv Summarizer
Generates a secure SECRET_KEY and helps with .env file setup
"""

import secrets
import os
import shutil

def generate_secret_key():
    """Generate a secure random SECRET_KEY"""
    return secrets.token_hex(32)

def setup_env_file():
    """Set up the .env file with generated SECRET_KEY"""
    secret_key = generate_secret_key()
    
    print("🔐 Generating secure SECRET_KEY...")
    print(f"Generated SECRET_KEY: {secret_key}")
    print()
    
    # Check if .env already exists
    if os.path.exists('.env'):
        print("⚠️  .env file already exists!")
        response = input("Do you want to overwrite it? (y/N): ").strip().lower()
        if response != 'y':
            print("❌ Setup cancelled. You can manually add the SECRET_KEY to your .env file:")
            print(f"SECRET_KEY={secret_key}")
            return
    
    # Copy .env.example to .env
    if os.path.exists('.env.example'):
        shutil.copy('.env.example', '.env')
        print("📄 Copied .env.example to .env")
        
        # Replace the placeholder SECRET_KEY
        with open('.env', 'r') as f:
            content = f.read()
        
        content = content.replace('your_secret_key_here_for_session_encryption', secret_key)
        
        with open('.env', 'w') as f:
            f.write(content)
        
        print("✅ .env file created with generated SECRET_KEY!")
        print()
        print("📝 Next steps:")
        print("1. Edit .env file and add your GEMINI_API_KEY")
        print("2. (Optional) Add Google OAuth credentials for sign-in features")
        print("3. Run: python app.py")
        
    else:
        print("❌ .env.example file not found!")
        print("Please create a .env file manually with:")
        print(f"SECRET_KEY={secret_key}")
        print("GEMINI_API_KEY=your_gemini_api_key_here")

def main():
    print("🚀 arXiv Summarizer - Quick Setup Helper")
    print("=" * 45)
    print()
    
    print("This script will help you:")
    print("• Generate a secure SECRET_KEY for Flask sessions")
    print("• Set up your .env configuration file")
    print()
    
    choice = input("Continue with setup? (Y/n): ").strip().lower()
    if choice == 'n':
        print("Setup cancelled.")
        return
    
    setup_env_file()

if __name__ == "__main__":
    main()
