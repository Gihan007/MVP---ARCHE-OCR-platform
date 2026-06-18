"""
Simple runner script for the Fax Ingress service (MVP)
"""
import sys
import os
from pathlib import Path

# Add parent directory to Python path so 'shared' module can be found
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import uvicorn

if __name__ == "__main__":
    print("Starting Fax Ingress API...")
    print("API will be available at: http://localhost:8001")
    print("Documentation at: http://localhost:8001/docs")
    print("\nPress Ctrl+C to stop\n")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )
