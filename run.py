"""
OCR-ArcheAI API Runner
Run the unified API server from the root directory
"""
import sys
import io
import os
from pathlib import Path

# Fix Unicode encoding on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Disable OneDNN/MKL-DNN BEFORE any PaddlePaddle imports to avoid compatibility issues on Windows
os.environ['FLAGS_use_mkldnn'] = 'False'
os.environ['FLAGS_use_cudnn'] = 'False'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['CPU_NUM'] = '1'
# Disable PIR (Program Intermediate Representation) which causes OneDNN issues in PaddlePaddle 3.0
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_enable_pir_in_executor'] = '0'

# Add root directory to Python path
root_dir = str(Path(__file__).parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Add fax_ingress to path so we can import app
fax_ingress_dir = str(Path(__file__).parent / "fax_ingress")
if fax_ingress_dir not in sys.path:
    sys.path.insert(0, fax_ingress_dir)

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("[API] Starting OCR-ArcheAI Unified API")
    print("=" * 60)
    print("\n[URL] API Server: http://localhost:8001")
    print("[URL] Swagger Docs: http://localhost:8001/docs")
    print("[URL] ReDoc: http://localhost:8001/redoc")
    print("\n[INGRESS] Endpoints: /upload, /jobs")
    print("[PROCESS] Endpoints: /process/{job_id}")
    print("\nPress Ctrl+C to stop\n")
    print("=" * 60)
    
    # Change working directory to fax_ingress so relative paths work
    os.chdir(fax_ingress_dir)
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )
