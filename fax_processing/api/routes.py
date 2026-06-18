"""
FastAPI routes for fax processing (OCR and extraction)
"""
from datetime import datetime
import logging
import sys
from pathlib import Path
from typing import Optional

from config.settings import settings
from fastapi import APIRouter, HTTPException, BackgroundTasks

# Setup logging
logger = logging.getLogger(__name__)

# Add parent directory to path to access shared module
parent_dir = str(Path(__file__).parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from shared.models.fax_job import FaxJob
from shared.database import SessionLocal

from models.schemas import (
    JobStatusResponse,
    ProcessRequest,
    ProcessResponse,
    ProcessLogResponse,
)
from core.storage import storage


router = APIRouter()

LOG_FILENAME = "processing.log"
ALLOWED_EXTENSIONS = ["pdf", "tif", "tiff", "png", "jpg", "jpeg"]


def _format_job_message(job_id: int, tenant_id: str, message: str) -> str:
    return f"[tenant={tenant_id}] job={job_id} {message}"


def _log_job_event(job_id: int, tenant_id: str, message: str, level: str = "info"):  # noqa: PLR0913
    timestamp = datetime.utcnow().isoformat()
    log_entry = f"{timestamp} {_format_job_message(job_id, tenant_id, message)}"
    log_fn = getattr(logger, level, logger.info)
    log_fn(log_entry)

    try:
        job_dir = storage._get_job_dir(job_id, tenant_id)
        job_log_path = job_dir / LOG_FILENAME
        with open(job_log_path, "a", encoding="utf-8") as output_file:
            output_file.write(log_entry + "\n")
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.debug("Failed to persist log for job %s: %s", job_id, exc)


def _resolve_job_log_path(job_id: int, tenant_id: str) -> Path:
    job_dir = storage.jobs_path

    if settings.ENABLE_TENANT_ISOLATION and tenant_id:
        job_dir = job_dir / tenant_id

    return job_dir / str(job_id) / LOG_FILENAME


def _read_job_log_entries(job_id: int, tenant_id: str, lines: int = 80) -> list[str]:
    log_path = _resolve_job_log_path(job_id, tenant_id)

    if not log_path.exists():
        return []

    with open(log_path, "r", encoding="utf-8") as log_file:
        raw = log_file.readlines()

    trimmed = [line.rstrip("\n") for line in raw[-lines:]]
    return trimmed


def _resolve_job_file(job_id: int, tenant_id: str) -> Path:
    storage_path = Path(__file__).parent.parent.parent / "fax_ingress" / "storage"
    patterns = [f"{tenant_id}_{job_id}_*.{ext}" for ext in ALLOWED_EXTENSIONS]
    fallback_patterns = [f"{tenant_id}_*.{ext}" for ext in ALLOWED_EXTENSIONS]

    for pattern in patterns + fallback_patterns:
        matches = sorted(storage_path.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]

    raise HTTPException(
        status_code=404,
        detail=f"No files found in storage for tenant '{tenant_id}' and job '{job_id}'"
    )


@router.post("/fax/process/{job_id}", response_model=ProcessResponse)
async def process_fax(
    job_id: int,
    background_tasks: BackgroundTasks,
    tenant_id: str = "default"
):
    """
    Process a fax document that was already uploaded via fax_ingress
    
    - **job_id**: Job ID from fax_ingress database
    - **tenant_id**: Tenant identifier
    
    This endpoint:
    1. Retrieves job info from shared database
    2. Loads file from storage/
    3. Splits into pages
    4. Runs OCR with PaddleOCR
    5. Extracts fields with bounding boxes
    6. Updates job status in database
    """
    try:
        # Get job from shared database
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            
            if not fax_job:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
            if fax_job.tenant_id != tenant_id:
                raise HTTPException(status_code=403, detail="Tenant mismatch")
            
            file_path = _resolve_job_file(job_id, tenant_id)
            _log_job_event(job_id, tenant_id, f"Found file: {file_path}")
            
            # Update job status to processing
            fax_job.status = "processing"
            db.commit()
            
        finally:
            db.close()
        
        # Trigger background processing
        background_tasks.add_task(
            _process_uploaded_file,
            job_id=job_id,
            tenant_id=tenant_id,
            file_path=file_path,
            db_instance=SessionLocal()
        )
        
        return ProcessResponse(
            job_id=job_id,
            status="processing",
            message=f"Processing started for job {job_id}",
            tenant_id=tenant_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process fax: {str(e)}"
        )


@router.get("/fax/job/{job_id}")
async def get_job_status(job_id: int, tenant_id: str = "default"):
    """
    Get status of a fax processing job from shared database
    
    - **job_id**: Job identifier (integer from database)
    - **tenant_id**: Tenant identifier (optional, for validation)
    """
    try:
        # Get job from shared database
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            
            if not fax_job:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found in database")
            
            # Optional: validate tenant_id matches
            if tenant_id and fax_job.tenant_id != tenant_id:
                logger.warning(f"Tenant mismatch: requested {tenant_id}, actual {fax_job.tenant_id}")
                # Don't fail, just warn for now (can be strict in production)
            
            return {
                "job_id": fax_job.id,
                "tenant_id": fax_job.tenant_id,
                "sha256": fax_job.sha256,
                "status": fax_job.status,
                "created_at": fax_job.created_at.isoformat() if fax_job.created_at else None,
                "finalized_at": fax_job.finalized_at.isoformat() if fax_job.finalized_at else None,
                "review_needed": fax_job.review_needed
            }
            
        finally:
            db.close()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job status: {str(e)}"
        )
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Count processed pages (those with OCR results)
        job_dir = storage._get_job_dir(job_id, tenant_id)
        ocr_dir = job_dir / "ocr_evidence"
        processed_pages = len(list(ocr_dir.glob("*.json"))) if ocr_dir.exists() else 0
        
        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            total_pages=job.total_pages,
            processed_pages=processed_pages,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_message=job.error_message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "PA Extraction API",
        "version": "1.0.0"
    }


@router.get("/fax/process/{job_id}/logs", response_model=ProcessLogResponse)
async def get_process_logs(job_id: int, tenant_id: str = "default", lines: int = 120):
    """Retrieve the most recent processing log entries for a given job"""
    try:
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()

            if not fax_job:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

            if tenant_id and fax_job.tenant_id != tenant_id:
                raise HTTPException(status_code=403, detail="Tenant mismatch")

            job_status = fax_job.status
        finally:
            db.close()

        entries = _read_job_log_entries(job_id, tenant_id, lines)

        return ProcessLogResponse(
            job_id=job_id,
            tenant_id=tenant_id,
            status=job_status,
            entries=entries,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to read logs: {e}")


# Background processing function
async def _process_uploaded_file(job_id: int, tenant_id: str, file_path: Path, db_instance):
    """
    Process uploaded file from fax_ingress
    This runs in the background after the API returns
    """
    try:
        _log_job_event(job_id, tenant_id, "Starting background processing")
        _log_job_event(job_id, tenant_id, f"File to process: {file_path}")
        
        # Update status to processing
        db = db_instance
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "processing"
                db.commit()
                _log_job_event(job_id, tenant_id, "Status updated to 'processing'")
        except Exception as e:
            _log_job_event(job_id, tenant_id, f"Failed to update job status: {e}", level="error")
        finally:
            db.close()
        
        # === ACTUAL PREPROCESSING STARTS HERE ===
        _log_job_event(job_id, tenant_id, "Starting preprocessing")
        
        # Create job-specific storage directory
        job_storage_dir = Path(f"fax_processing/storage/jobs/{tenant_id}/{job_id}")
        job_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Split PDF into pages and preprocess
        from core.preprocessing import preprocessor
        
        _log_job_event(job_id, tenant_id, "Splitting PDF and preprocessing pages")
        total_pages = preprocessor.process_document(
            job_id=str(job_id),  # Convert to string for storage system
            tenant_id=tenant_id,
            file_path=file_path
        )
        
        _log_job_event(job_id, tenant_id, f"Preprocessing complete: {total_pages} pages extracted and cleaned")
        
        # Update status to preprocessed
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "preprocessed"
                db.commit()
                _log_job_event(job_id, tenant_id, "Status updated to 'preprocessed'")
        finally:
            db.close()
        
        # === OCR EXTRACTION WITH TOKENS + BOUNDING BOXES ===
        _log_job_event(job_id, tenant_id, f"Starting OCR extraction for {total_pages} pages")
        
        from core.ocr_engine import ocr_engine
        
        # Process each page with OCR
        for page_num in range(1, total_pages + 1):
            # Resolve page image path via storage manager (uses absolute base path)
            page_image_path = storage._get_page_dir(job_id, tenant_id, page_num) / f"page_{page_num:04d}.png"
            
            if page_image_path.exists():
                _log_job_event(job_id, tenant_id, f"Running OCR on page {page_num}/{total_pages}")
                
                # Extract tokens + bounding boxes + confidence scores
                page_metadata = ocr_engine.process_page(
                    job_id=str(job_id),
                    tenant_id=tenant_id,
                    page_num=page_num,
                    page_image_path=page_image_path
                )
                
                _log_job_event(job_id, tenant_id, f"Page {page_num}: Extracted {len(page_metadata.ocr_tokens)} tokens")
            else:
                _log_job_event(job_id, tenant_id, f"Page image not found: {page_image_path}", level="warning")
        
        # Update final status to ocr_complete
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "ocr_complete"
                db.commit()
                _log_job_event(job_id, tenant_id, "Job OCR complete! Status: 'ocr_complete'")
        finally:
            db.close()
            
    except Exception as e:
        _log_job_event(job_id, tenant_id, "Background processing failed", level="error")
        logger.error(f"Background processing failed for job {job_id}: {e}", exc_info=True)
        # Update job status to failed
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "failed"
                db.commit()
        finally:
            db.close()
