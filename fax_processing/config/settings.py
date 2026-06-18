"""
Configuration settings for PA Extraction System
"""
from pydantic_settings import BaseSettings
from pathlib import Path
import sys
import os

# Add parent directory to path to access shared module
parent_dir = str(Path(__file__).parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)


class Settings(BaseSettings):
    # API Settings
    APP_NAME: str = "Prior Authorization Extraction API"
    API_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8001  # Changed from 8000 to avoid conflict with fax_ingress
    DEBUG: bool = True
    
    # Database Settings (use shared database)
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/fax_db"
    
    # Storage Settings
    # In Docker: volume mount ./storage:/app/storage  
    # Primary path for Docker is /app/storage
    BASE_STORAGE_PATH: Path = Path("/app/storage") if Path("/app").exists() else Path(__file__).parent.parent / "storage"
    JOBS_PATH: Path = BASE_STORAGE_PATH / "jobs"
    PAGES_PATH: Path = BASE_STORAGE_PATH / "pages"
    OCR_RESULTS_PATH: Path = BASE_STORAGE_PATH / "ocr_results"
    TEMPLATES_PATH: Path = BASE_STORAGE_PATH / "templates"
    
    # OCR Settings
    OCR_LANG: str = "en"
    OCR_DPI: int = 150  # ⚡ OPTIMIZED: 150 DPI (was 300) - halves image size = ~50% faster OCR, still readable for text
    OCR_VERSION: str = "PP-OCRv3"  # ⚡ SPEED: PP-OCRv3 is ~40% faster than v4 (lighter rec model, same det model)
    OCR_DET_MODEL: str = "en_PP-OCRv3_det"  # Same det model used by v3 and v4
    OCR_REC_MODEL: str = "en_PP-OCRv3_rec"  # Lighter recognition model = faster
    OCR_DET_BOX_THRESH: float = 0.3
    OCR_DET_UNCLIP_RATIO: float = 2.0
    OCR_REC_BATCH_NUM: int = 32  # Batch size for recognition (higher = faster but uses more memory)
    OCR_CPU_THREADS: int = 4  # CPU threads for OCR (adjust based on your machine)
    OCR_USE_ANGLE_CLS: bool = False  # ⚡ OPTIMIZED: Disable angle classification (saves ~0.2s per page, fax pages are always upright)
    
    # Processing Settings
    MAX_FILE_SIZE_MB: int = 50
    SUPPORTED_FORMATS: list = [".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"]
    
    # Tenant/HIPAA Settings
    ENABLE_TENANT_ISOLATION: bool = True
    ENABLE_ENCRYPTION: bool = False  # For later
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables


settings = Settings()

# Ensure storage directories exist
for path in [
    settings.JOBS_PATH,
    settings.PAGES_PATH,
    settings.OCR_RESULTS_PATH,
    settings.TEMPLATES_PATH,
]:
    path.mkdir(parents=True, exist_ok=True)
