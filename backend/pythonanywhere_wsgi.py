"""
WSGI wrapper for PythonAnywhere deployment.
Point PythonAnywhere Web App to this file.
"""
import sys
import os
from pathlib import Path

# Add backend dir to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Load .env if present
from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

# Import the FastAPI app
from app import app as application
