"""
Simple runner script for the Fax Processing service
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
    print("Starting Fax Processing API...")
    print("API will be available at: http://localhost:8002")
    print("Documentation at: http://localhost:8002/api/v1/docs")
    print("\nPress Ctrl+C to stop\n")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )
