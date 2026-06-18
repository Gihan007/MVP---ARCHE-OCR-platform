from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

# Load .env file from project root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/fax_db"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Object Storage
    storage_bucket: str = "fax-documents"
    storage_access_key: str = "your_access_key"
    storage_secret_key: str = "your_secret_key"
    
    # API Keys
    openai_api_key: str = ""
    
    # Multi-tenant
    tenant_id: str = "default"
    
    # OCR/VLM Config
    ocr_model_path: str = "models/paddleocr"
    vlm_model_path: str = "models/donut"
    vlm_backend: str = "openai"  # options: openai, donut
    
    # Security
    secret_key: str = "your_secret_key"
    hipaa_compliance_mode: bool = True

    class Config:
        env_file = env_path
        extra = "ignore"  # Ignore extra environment variables

settings = Settings()