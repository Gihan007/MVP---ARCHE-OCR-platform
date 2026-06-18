"""
Storage management for fax jobs, pages, and OCR results
"""
import json
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime
import numpy as np
from fax_processing.config.settings import settings
from shared.models.fax_job import FaxJob
from fax_processing.models.schemas import PageMetadata, JobStatus


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, (np.ndarray, np.generic)):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.int_)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float_)):
            return float(obj)
        return super().default(obj)


class StorageManager:
    """Manages file system storage for jobs and artifacts"""
    
    def __init__(self):
        self.jobs_path = settings.JOBS_PATH
        self.pages_path = settings.PAGES_PATH
        self.ocr_path = settings.OCR_RESULTS_PATH
    
    def compute_sha256(self, file_content: bytes) -> str:
        """Compute SHA256 hash of file content"""
        return hashlib.sha256(file_content).hexdigest()
    
    def save_original_file(self, job_id: int, tenant_id: str, content: bytes, filename: str) -> Path:
        """Save original fax file"""
        job_dir = self._get_job_dir(job_id, tenant_id)
        file_path = job_dir / "original" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        return file_path
    
    def save_job_metadata(self, job: FaxJob) -> None:
        """Save job metadata as JSON"""
        job_dir = self._get_job_dir(job.id, job.tenant_id)
        metadata_path = job_dir / "job_metadata.json"
        
        with open(metadata_path, "w") as f:
            json.dump(job.model_dump(mode='json'), f, indent=2, default=str)
    
    def load_job_metadata(self, job_id: int, tenant_id: str) -> Optional[FaxJob]:
        """Load job metadata from JSON"""
        job_dir = self._get_job_dir(job_id, tenant_id)
        metadata_path = job_dir / "job_metadata.json"
        
        if not metadata_path.exists():
            return None
        
        with open(metadata_path, "r") as f:
            data = json.load(f)
            return FaxJob(**data)
    
    def update_job_status(self, job_id: int, tenant_id: str, status: JobStatus, 
                         error_message: Optional[str] = None) -> None:
        """Update job status"""
        job = self.load_job_metadata(job_id, tenant_id)
        if job:
            job.status = status
            job.updated_at = datetime.utcnow()
            if error_message:
                job.error_message = error_message
            self.save_job_metadata(job)
    
    def save_page_image(self, job_id: int, tenant_id: str, page_num: int, 
                       image_bytes: bytes, extension: str = ".png") -> Path:
        """Save individual page image"""
        page_dir = self._get_page_dir(job_id, tenant_id, page_num)
        page_path = page_dir / f"page_{page_num:04d}{extension}"
        
        with open(page_path, "wb") as f:
            f.write(image_bytes)
        
        return page_path
    
    def save_page_metadata(self, page_meta: PageMetadata, tenant_id: str = "") -> None:
        """Save page metadata including OCR tokens"""
        page_dir = self._get_page_dir(page_meta.job_id, tenant_id, page_meta.page_num)
        metadata_path = page_dir / "page_metadata.json"
        
        with open(metadata_path, "w") as f:
            json.dump(page_meta.model_dump(mode='json'), f, indent=2, cls=NumpyEncoder)
    
    def save_ocr_results(self, job_id: int, tenant_id: str, page_num: int, 
                        ocr_data: dict) -> Path:
        """Save raw OCR results for evidence"""
        ocr_dir = self._get_job_dir(job_id, tenant_id) / "ocr_evidence"
        ocr_dir.mkdir(parents=True, exist_ok=True)
        ocr_path = ocr_dir / f"page_{page_num:04d}_ocr.json"
        
        with open(ocr_path, "w") as f:
            json.dump(ocr_data, f, indent=2, cls=NumpyEncoder)
        
        return ocr_path
    
    def _get_job_dir(self, job_id: int, tenant_id: str) -> Path:
        """Get job directory path with tenant isolation"""
        job_id_str = str(job_id)
        if settings.ENABLE_TENANT_ISOLATION and tenant_id:
            job_dir = self.jobs_path / tenant_id / job_id_str
        else:
            job_dir = self.jobs_path / job_id_str
        
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir
    
    def _get_page_dir(self, job_id: int, tenant_id: str, page_num: int) -> Path:
        """Get page directory path"""
        page_dir = self._get_job_dir(job_id, tenant_id) / "pages" / f"page_{page_num:04d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        return page_dir


# Singleton instance
storage = StorageManager()
