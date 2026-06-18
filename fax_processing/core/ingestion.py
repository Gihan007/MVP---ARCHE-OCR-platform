"""
Fax ingestion module - handles file upload, validation, job creation
"""
import uuid
from pathlib import Path
from typing import Tuple
from fastapi import UploadFile, HTTPException
from datetime import datetime

from shared.models.fax_job import FaxJob
from fax_processing.models.schemas import JobStatus, FaxIngestRequest
from fax_processing.core.storage import storage
from fax_processing.config.settings import settings


class FaxIngestor:
    """Handles fax file ingestion and initial processing"""
    
    def __init__(self):
        self.max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        self.supported_formats = settings.SUPPORTED_FORMATS
    
    async def ingest_fax(self, file: UploadFile, request: FaxIngestRequest) -> FaxJob:
        """
        Ingest a fax file and create a job
        
        Steps:
        1. Validate file format and size
        2. Generate job_id
        3. Read file content and compute SHA256
        4. Save original file
        5. Create job metadata
        6. Return job object
        """
        # Validate file
        self._validate_file(file)
        
        # Generate job ID
        job_id = self._generate_job_id()
        
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Compute SHA256 for deduplication/integrity
        file_hash = storage.compute_sha256(content)
        
        # Save original file
        original_path = storage.save_original_file(
            job_id=job_id,
            tenant_id=request.tenant_id,
            content=content,
            filename=file.filename or "fax_document"
        )
        
        # Create job metadata
        job = FaxJob(
            job_id=job_id,
            tenant_id=request.tenant_id,
            original_filename=file.filename or "unknown",
            file_sha256=file_hash,
            file_size_bytes=file_size,
            total_pages=0,  # Will be updated after page splitting
            status=JobStatus.PENDING,
            metadata=request.metadata or {}
        )
        
        # Save job metadata
        storage.save_job_metadata(job)
        
        return job
    
    def _validate_file(self, file: UploadFile) -> None:
        """Validate file format and constraints"""
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        
        # Check file extension
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in self.supported_formats:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format. Supported: {', '.join(self.supported_formats)}"
            )
    
    def _generate_job_id(self) -> str:
        """Generate unique job ID"""
        return f"job_{uuid.uuid4().hex[:12]}_{int(datetime.utcnow().timestamp())}"


# Singleton instance
fax_ingestor = FaxIngestor()
