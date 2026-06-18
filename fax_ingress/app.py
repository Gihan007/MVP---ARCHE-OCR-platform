# Disable OneDNN/MKL-DNN BEFORE any PaddlePaddle imports to avoid compatibility issues on Windows
import os
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_use_cudnn'] = '0'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['CPU_NUM'] = '1'
# Disable PIR (Program Intermediate Representation) which causes OneDNN issues in PaddlePaddle 3.0
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_enable_pir_in_executor'] = '0'
os.environ['FLAGS_use_onednn'] = '0'

from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles
import hashlib
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from shared.models.fax_job import FaxJob
from shared.models.fax_extracted_field import FaxExtractedField
from shared.models.human_label import HumanLabel
from shared.config.settings import settings
from shared.database import get_db, SessionLocal
from fax_ingress.core.hybrid_classifier import classify_document
import logging
import httpx
from pathlib import Path

def processing_jobs_path() -> Path:
    """Return the shared processing jobs directory for local and Docker runs."""
    if Path("/app/storage").exists() or Path("/app").exists():
        return Path("/app/storage/jobs")
    return Path(__file__).parent.parent / "storage" / "jobs"

def count_job_pages(tenant_id: str, job_id: int) -> int:
    """Count actual pages for a job from fax_processing storage"""
    pages_dir = processing_jobs_path() / tenant_id / str(job_id) / "pages"
    print(f"DEBUG: Looking for pages in: {pages_dir}")
    print(f"DEBUG: Directory exists: {pages_dir.exists()}")
    if pages_dir.exists():
        page_dirs = [d for d in pages_dir.iterdir() if d.is_dir() and d.name.startswith("page_")]
        print(f"DEBUG: Found page directories: {[d.name for d in page_dirs]}")
        return len(page_dirs)
    print(f"DEBUG: Pages directory not found")
    return 0

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Debug database URL
logger.info(f"Database URL: {settings.database_url}")
logger.info(f"Current working directory: {os.getcwd()}")

app = FastAPI(
    title="OCR-ArcheAI API",
    description="Unified API for fax ingestion and OCR processing",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Ingress",
            "description": "📥 **File Upload & Management** - Upload fax documents, query jobs, list submissions"
        },
        {
            "name": "Processing",
            "description": "⚙️ **OCR Processing** - Trigger document processing, page splitting, OCR extraction with bounding boxes"
        },
        {
            "name": "Review",
            "description": "👁️ **Human Review Interface** - Review AI extractions, provide corrections, create training labels"
        },
        {
            "name": "Health",
            "description": "🏥 **System Health** - Health checks and service status"
        }
    ]
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure storage directory exists
STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)
logger.info(f"Storage directory ready: {STORAGE_DIR}")

ALLOWED_TYPES = {"application/pdf", "image/tiff", "image/jpeg", "image/png"}
ALLOWED_EXTENSIONS = ["pdf", "tif", "tiff", "png", "jpg", "jpeg"]


class BulkProcessRequest(BaseModel):
    job_ids: List[int]
    tenant_id: str = "default"


def _safe_filename(original_name: str) -> str:
    safe_characters = [c if c.isalnum() or c in [".", "_", "-"] else "_" for c in original_name]
    return "".join(safe_characters)


def _resolve_job_file(job_id: int, tenant_id: str) -> Path:
    """
    Resolve and return absolute path to a job's file from storage
    
    Returns: Absolute Path object to the file
    Raises: HTTPException if file not found
    """
    storage_path = Path(STORAGE_DIR).resolve()  # Convert to absolute path
    patterns = [f"{tenant_id}_{job_id}_*.{ext}" for ext in ALLOWED_EXTENSIONS]
    fallback_patterns = [f"{tenant_id}_*.{ext}" for ext in ALLOWED_EXTENSIONS]

    for pattern in patterns + fallback_patterns:
        matches = sorted(storage_path.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        if matches:
            absolute_path = matches[0].resolve()  # Ensure absolute path
            return absolute_path

    raise HTTPException(
        status_code=404,
        detail=f"No files found in storage for tenant '{tenant_id}' and job '{job_id}'"
    )


async def _ingest_upload_file(upload_file: UploadFile, tenant_id: str, db: Session, index: int = 0):
    if upload_file.content_type and upload_file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {upload_file.content_type}. Supported types: PDF, TIFF, JPEG, PNG"
        )

    content = await upload_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = db.query(FaxJob).filter(FaxJob.sha256 == sha256).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate PDF: already exists with job ID {existing.id}"
        )

    safe_filename = _safe_filename(upload_file.filename or "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"{tenant_id}_{timestamp}_{index}_{safe_filename}"
    temp_path = Path(STORAGE_DIR) / temp_filename

    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(content)

    fax_job = FaxJob(
        tenant_id=tenant_id,
        sha256=sha256,
        status="ingested",
        created_at=datetime.utcnow(),
        review_needed=False
    )
    db.add(fax_job)
    db.commit()
    db.refresh(fax_job)

    final_filename = f"{tenant_id}_{fax_job.id}_{timestamp}_{safe_filename}"
    final_path = temp_path.with_name(final_filename)
    temp_path.rename(final_path)

    return {
        "fax_job_id": fax_job.id,
        "sha256": sha256,
        "file_size": len(content),
        "filename": final_filename,
        "file_path": str(final_path.resolve()),
        "status": "ingested"
    }


async def _ingest_upload_file_from_bytes(
    content: bytes,
    filename: str,
    content_type: str,
    tenant_id: str,
    db: Session,
    index: int = 0
):
    """
    Ingest a file from raw bytes content (used for pre-classified documents).
    This is the same as _ingest_upload_file but takes bytes directly instead of UploadFile.
    """
    if content_type and content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Supported types: PDF, TIFF, JPEG, PNG"
        )

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = db.query(FaxJob).filter(FaxJob.sha256 == sha256).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate PDF: already exists with job ID {existing.id}"
        )

    safe_filename = _safe_filename(filename or "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"{tenant_id}_{timestamp}_{index}_{safe_filename}"
    temp_path = Path(STORAGE_DIR) / temp_filename

    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(content)

    fax_job = FaxJob(
        tenant_id=tenant_id,
        sha256=sha256,
        status="ingested",
        created_at=datetime.utcnow(),
        review_needed=False
    )
    db.add(fax_job)
    db.commit()
    db.refresh(fax_job)

    final_filename = f"{tenant_id}_{fax_job.id}_{timestamp}_{safe_filename}"
    final_path = temp_path.with_name(final_filename)
    temp_path.rename(final_path)
    
    # Resolve to absolute path for local processing.
    final_path_absolute = final_path.resolve()

    return {
        "fax_job_id": fax_job.id,
        "sha256": sha256,
        "file_size": len(content),
        "filename": final_filename,
        "file_path": str(final_path_absolute),
        "status": "ingested"
    }


# Mount static files
app.mount("/storage", StaticFiles(directory="storage"), name="storage")
# Note: fax_processing storage will be served via API routes instead of direct mounting

# ===== HUMAN REVIEW ENDPOINTS =====

@app.get("/review-ui/{fax_job_id}", tags=["Review"], response_class=HTMLResponse)
async def review_ui(fax_job_id: int):
    """Serve the human review interface"""
    try:
        template_path = Path(__file__).parent / "templates" / "review.html"
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Inject job ID into the HTML
        html_content = html_content.replace(
            "currentJobId = null;",
            f"currentJobId = {fax_job_id};"
        )

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"Error serving review UI for job {fax_job_id}: {e}")
        return HTMLResponse(content=f"<h1>Error loading review interface: {e}</h1>", status_code=500)


@app.get("/review/queue", tags=["Review"])
async def get_review_queue(
    limit: int = 10,
    reviewer_id: str = None,
    db: Session = Depends(get_db)
):
    """Get jobs that need human review"""
    try:
        query = db.query(FaxJob).filter(
            FaxJob.status == "completed",
            # FaxJob.review_needed == True
        ).order_by(FaxJob.created_at.desc())

        if reviewer_id:
            # Could add reviewer assignment logic here
            pass

        jobs = query.limit(limit).all()

        queue_data = []
        for job in jobs:
            # Count fields needing review
            low_confidence_fields = db.query(FaxExtractedField).filter(
                FaxExtractedField.fax_job_id == job.id,
                FaxExtractedField.confidence < 0.8
            ).count()

            queue_data.append({
                "job_id": job.id,
                "tenant_id": job.tenant_id,
                "created_at": job.created_at,
                "total_pages": job.total_pages,
                "fields_needing_review": low_confidence_fields,
                "priority": "high" if low_confidence_fields > 5 else "medium"
            })

        return {"review_queue": queue_data, "total_pending": len(queue_data)}

    except Exception as e:
        logger.error(f"Error getting review queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/review/{fax_job_id}", tags=["Review"])
async def get_review_data(fax_job_id: int, db: Session = Depends(get_db)):
    """Get data needed for human review of AI extractions"""
    try:
        # Get job info
        fax_job = db.query(FaxJob).filter(FaxJob.id == fax_job_id).first()
        if not fax_job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Get extracted fields
        extracted_fields = db.query(FaxExtractedField).filter(
            FaxExtractedField.fax_job_id == fax_job_id
        ).all()

        # Get existing human labels (latest for each field)
        human_labels_raw = db.query(HumanLabel).filter(
            HumanLabel.fax_job_id == fax_job_id
        ).order_by(HumanLabel.field_key, HumanLabel.created_at.desc()).all()

        # Group by field_key and keep only the latest
        human_labels = {}
        for hl in human_labels_raw:
            if hl.field_key not in human_labels:
                human_labels[hl.field_key] = hl

        # Build review data structure
        actual_pages = count_job_pages(fax_job.tenant_id, fax_job_id)
        review_data = {
            "job_id": fax_job_id,
            "status": fax_job.status,
            "total_pages": actual_pages,
            "pages": []
        }

        field_entries = []
        for field in extracted_fields:
            human_label = human_labels.get(field.field_key)
            method_value = field.method or "AI"
            method_key = method_value.upper()
            if method_key == "LLM":
                source_label = "LLM"
            elif method_key == "VLM":
                source_label = "VLM"
            else:
                source_label = "AI"

            confidence_value = field.confidence
            requires_review_flag = (
                isinstance(confidence_value, float) or isinstance(confidence_value, int)
            ) and confidence_value < 0.8

            validation_errors = field.evidence_text if field.evidence_text else ""

            field_entries.append({
                "field_key": field.field_key,
                "ai_value": field.value,
                "ai_confidence": confidence_value,
                "method": method_value,
                "source": source_label,
                "bbox": field.evidence_bbox,
                "evidence_text": field.evidence_text,
                "validation_errors": validation_errors,
                "requires_review": requires_review_flag,
                "validated": field.validated,
                "human_reviewed": human_label is not None,
                "human_value": human_label.human_value if human_label else None,
                "human_action": human_label.human_action if human_label else None,
                "last_reviewed_at": human_label.created_at.isoformat() if human_label and human_label.created_at else None,
                "reviewer_id": human_label.reviewer_id if human_label else None
            })

        page_data = {}
        for page_num in range(1, actual_pages + 1):
            page_data[page_num] = {
                "page_num": page_num,
                "image_url": f"/fax_processing_storage/jobs/{fax_job.tenant_id}/{fax_job_id}/pages/{page_num:04d}/page_{page_num:04d}.png",
                "fields": [entry.copy() for entry in field_entries]
            }

        review_data["pages"] = list(page_data.values())
        review_data["fields"] = field_entries

        return review_data

    except Exception as e:
        logger.error(f"Error getting review data for job {fax_job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/review/{fax_job_id}/submit", tags=["Review"])
async def submit_review(
    fax_job_id: int,
    review_data: dict,
    reviewer_id: str = "default_reviewer",
    db: Session = Depends(get_db)
):
    """Submit human review corrections and create training labels"""
    try:
        import time
        start_time = time.time()

        # Validate job exists
        fax_job = db.query(FaxJob).filter(FaxJob.id == fax_job_id).first()
        if not fax_job:
            raise HTTPException(status_code=404, detail="Job not found")

        corrections = review_data.get("corrections", [])
        total_review_time = 0
        modified_field_names = []  # Track which fields were modified

        import os
        notes_path = os.path.join(os.path.dirname(__file__), "review_notes.txt")
        with open(notes_path, "a", encoding="utf-8") as notes_file:
            for correction in corrections:
                field_key = correction["field_key"]
                human_value = correction.get("human_value", "").strip()
                action = correction.get("action", "accept")  # accept, edit, reject
                page_number = correction.get("page_number", 1)
                bbox = correction.get("bbox")
                human_note = correction.get("human_note", "").strip()

                # Save note if present
                if human_note:
                    notes_file.write(f"Field {field_key}, Page {page_number}: {human_note}\n")

                # Get original AI extraction
                ai_field = db.query(FaxExtractedField).filter(
                    FaxExtractedField.fax_job_id == fax_job_id,
                    FaxExtractedField.field_key == field_key
                ).first()

                if not ai_field:
                    continue

                # Check if human label already exists for this field
                existing_human_label = db.query(HumanLabel).filter(
                    HumanLabel.fax_job_id == fax_job_id,
                    HumanLabel.field_key == field_key
                ).first()

                if existing_human_label:
                    # Update existing human label
                    existing_human_label.human_value = human_value if action != "reject" else None
                    existing_human_label.human_action = action
                    existing_human_label.reviewer_id = reviewer_id
                    existing_human_label.page_number = page_number
                    existing_human_label.bbox = bbox
                    existing_human_label.created_at = datetime.utcnow()  # Update timestamp
                    human_label = existing_human_label
                else:
                    # Create new human label record
                    human_label = HumanLabel(
                        fax_job_id=fax_job_id,
                        field_key=field_key,
                        ai_value=ai_field.value,
                        ai_confidence=ai_field.confidence,
                        human_value=human_value if action != "reject" else None,
                        human_action=action,
                        reviewer_id=reviewer_id,
                        page_number=page_number,
                        bbox=bbox
                    )
                    db.add(human_label)

                # Update the extracted field with human correction
                if action == "accept":
                    ai_field.validated = "valid"
                    ai_field.value = ai_field.value  # Keep AI value
                elif action == "edit":
                    ai_field.validated = "valid"
                    # Store original AI value before modification
                    if not ai_field.original_ai_value:
                        ai_field.original_ai_value = ai_field.value
                    ai_field.value = human_value  # Use human correction
                    ai_field.method = "HUMAN_CORRECTED"
                    ai_field.human_modified = True
                    ai_field.human_modified_at = datetime.utcnow()
                    ai_field.human_modified_by = reviewer_id
                    modified_field_names.append(field_key)  # Track modification
                elif action == "reject":
                    ai_field.validated = "invalid"
                    # Store original AI value before modification
                    if not ai_field.original_ai_value:
                        ai_field.original_ai_value = ai_field.value
                    ai_field.value = None
                    ai_field.human_modified = True
                    ai_field.human_modified_at = datetime.utcnow()
                    ai_field.human_modified_by = reviewer_id
                    modified_field_names.append(field_key)  # Track modification

        # Update job-level modification tracking
        if modified_field_names:
            fax_job.has_human_modifications = True
            fax_job.modified_fields = ",".join(sorted(set(modified_field_names)))  # Remove duplicates and sort
        else:
            fax_job.has_human_modifications = False
            fax_job.modified_fields = None

        # Mark job as reviewed
        fax_job.review_needed = False
        fax_job.finalized_at = datetime.utcnow()

        db.commit()

        total_time = time.time() - start_time
        return {
            "status": "success",
            "message": f"Review submitted for {len(corrections)} fields",
            "review_time_seconds": total_time,
            "corrections_applied": len(corrections),
            "fields_modified": len(modified_field_names)
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting review for job {fax_job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API info"""
    return {
        "service": "OCR-ArcheAI API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/fax_processing_storage/jobs/{tenant_id}/{job_id}/pages/{page_num}/{filename}")
async def serve_fax_processing_image(tenant_id: str, job_id: str, page_num: str, filename: str):
    """Serve images from fax_processing storage"""
    # Convert page_num to int and format it properly
    try:
        page_num_int = int(page_num)
        page_dir = f"page_{page_num_int:04d}"
    except ValueError:
        page_dir = f"page_{page_num}"

    file_path = processing_jobs_path() / tenant_id / job_id / "pages" / page_dir / filename
    print(f"DEBUG: Route matched - tenant_id: {tenant_id}, job_id: {job_id}, page_num: {page_num}, filename: {filename}")
    print(f"DEBUG: Page dir: {page_dir}")
    print(f"DEBUG: Looking for file at: {file_path}")
    print(f"DEBUG: File exists: {file_path.exists()}")
    if file_path.exists():
        return FileResponse(file_path)
    else:
        print(f"DEBUG: Image not found at: {file_path}")
        raise HTTPException(status_code=404, detail="Image not found")


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ocr_archeai"}


# ===== READ-ONLY DATABASE BROWSER ENDPOINTS =====

def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _get_database_tables(db: Session):
    inspector = inspect(db.bind)
    return sorted(inspector.get_table_names())


@app.get("/database/tables", tags=["Database"])
async def list_database_tables(db: Session = Depends(get_db)):
    """List database tables and columns for the read-only UI browser."""
    try:
        inspector = inspect(db.bind)
        tables = []

        for table_name in sorted(inspector.get_table_names()):
            quoted_table = _quote_identifier(table_name)
            row_count = db.execute(text(f"SELECT COUNT(*) FROM {quoted_table}")).scalar()
            columns = [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": bool(column.get("nullable")),
                    "primary_key": bool(column.get("primary_key")),
                }
                for column in inspector.get_columns(table_name)
            ]
            tables.append({
                "name": table_name,
                "row_count": row_count,
                "columns": columns,
            })

        return {"tables": tables}
    except Exception as exc:
        logger.error("Error listing database tables: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/database/tables/{table_name}", tags=["Database"])
async def get_database_table_rows(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return rows from a selected table. Read-only and limited for safety."""
    try:
        tables = _get_database_tables(db)
        if table_name not in tables:
            raise HTTPException(status_code=404, detail="Table not found")

        safe_limit = min(max(limit, 1), 200)
        safe_offset = max(offset, 0)
        quoted_table = _quote_identifier(table_name)
        inspector = inspect(db.bind)

        columns = [column["name"] for column in inspector.get_columns(table_name)]
        total = db.execute(text(f"SELECT COUNT(*) FROM {quoted_table}")).scalar()
        rows = db.execute(
            text(f"SELECT * FROM {quoted_table} LIMIT :limit OFFSET :offset"),
            {"limit": safe_limit, "offset": safe_offset},
        ).mappings().all()

        return {
            "table": table_name,
            "columns": columns,
            "rows": [dict(row) for row in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error reading database table %s: %s", table_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/upload", tags=["Ingress"])
async def upload_fax(
    file: UploadFile = File(...),
    tenant_id: str = Form(default="default"),
    auto_process: bool = Form(default=False),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Upload a fax document for processing
    
    Workflow:
    1. CLASSIFY document first (PyMuPDF + TinyOCR)
    2. Only ACCEPT and SAVE PA documents
    3. REJECT non-PA documents
    
    Args:
        file: PDF or image file (TIFF, JPEG, PNG)
        tenant_id: Tenant identifier (default: "default")
        auto_process: Automatically trigger OCR processing (default: False)
        db: Database session
        
    Returns:
        JSON with fax_job_id, sha256, file_size, and status (only for PA documents)
        OR error response for non-PA documents
    """
    logger.info(f"Upload started - Tenant: {tenant_id}, Filename: {file.filename}")

    try:
        # STEP 1: Read file to temp location for classification
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        
        # Save to temp file for classification
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            temp_file_path = tmp.name
            tmp.write(content)
        
        # STEP 2: CLASSIFY DOCUMENT FIRST (before saving to database)
        logger.info(f"Classifying document: {file.filename}")
        try:
            classification_result = classify_document(temp_file_path)
            
            logger.info(
                f"Document classification result - Type: {classification_result.document_type}, "
                f"Confidence: {classification_result.confidence:.2f}, "
                f"Payer: {classification_result.matched_payer}, "
                f"Method: {classification_result.extraction_method}, "
                f"Time: {classification_result.processing_time_ms:.0f}ms"
            )
            
            # STEP 3: REJECT if NOT PA or low confidence (lowered threshold from 0.70 to 0.60)
            if classification_result.document_type != "prior_authorization" or classification_result.confidence < 0.60:
                logger.warning(
                    f"Document rejected - Not a PA or low confidence: "
                    f"Type={classification_result.document_type}, "
                    f"Confidence={classification_result.confidence:.2f}"
                )
                Path(temp_file_path).unlink(missing_ok=True)
                
                return JSONResponse({
                    "message": "Document rejected",
                    "reason": f"This is not a Prior Authorization document (Type: {classification_result.document_type}, Confidence: {classification_result.confidence:.0%})",
                    "status": "rejected",
                    "filename": file.filename
                }, status_code=400)
            
            # STEP 4: ACCEPT PA - Save to database with SHA
            logger.info(f"Document accepted as PA - Proceeding with ingestion")
            
            # Clean up temp file
            Path(temp_file_path).unlink(missing_ok=True)
            
            # Now save to database with SHA
            ingest_result = await _ingest_upload_file_from_bytes(content, file.filename, file.content_type, tenant_id, db)
            fax_job_id = ingest_result["fax_job_id"]
            file_path = ingest_result["file_path"]  # Use the actual file path from ingest
            
            logger.info(f"PA Document accepted: FaxJob created with ID: {fax_job_id}")
            
            processing_status = None
            if auto_process:
                processing_status = "processing"
                if background_tasks:
                    background_tasks.add_task(
                        _process_uploaded_file,
                        job_id=fax_job_id,
                        tenant_id=tenant_id,
                        file_path=Path(file_path),
                    )
                    logger.info(f"Queued local processing for job {fax_job_id}")
                else:
                    _process_uploaded_file(
                        job_id=fax_job_id,
                        tenant_id=tenant_id,
                        file_path=Path(file_path),
                    )
                    processing_status = "completed"
            # Return success response
            response_data = {
                **ingest_result,
                "message": "PA document uploaded successfully",
                "classification": {
                    "document_type": classification_result.document_type,
                    "confidence": f"{classification_result.confidence:.0%}",
                    "detected_payer": classification_result.matched_payer
                }
            }
            
            if auto_process:
                if processing_status == "processing":
                    response_data["processing_status"] = "processing"
                    response_data["status_url"] = f"/jobs/{fax_job_id}/summary"
                elif processing_status == "completed":
                    response_data["processing_status"] = "completed"
                    response_data["status"] = "completed"
                else:
                    response_data["processing_status"] = processing_status or "failed"
                    response_data["next_step"] = f"Process at: /process/{fax_job_id}"
            else:
                response_data["next_step"] = f"Process at: /process/{fax_job_id}"
            
            return JSONResponse(response_data, status_code=201)

        except Exception as classify_error:
            logger.error(f"Classification error: {classify_error}", exc_info=True)
            Path(temp_file_path).unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Classification failed: {str(classify_error)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during upload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/upload/complete", tags=["Ingress"])
async def upload_and_complete(
    file: UploadFile = File(...),
    tenant_id: str = Form(default="default"),
    auto_process: bool = Form(default=True),
    db: Session = Depends(get_db)
):
    """
    One‑shot route that uploads a single fax and waits for the full processing
    pipeline to finish.  The response includes the ingestion metadata, the
    processing result and the final summary/fields.

    WARNING: this endpoint blocks until local processing completes, so it may
    take several seconds (or minutes) depending on document size.  Use it for
    convenience in scripts or when you want a synchronous API.
    """

    # ingest file exactly as /upload does
    ingest_res = await _ingest_upload_file(file, tenant_id, db)
    job_id = ingest_res["fax_job_id"]

    # optionally trigger processing and wait for completion
    if auto_process:
        processing_result = _process_uploaded_file(
            job_id=job_id,
            tenant_id=tenant_id,
            file_path=Path(ingest_res["file_path"]),
        )
        summary = await get_job_summary(job_id, tenant_id, db)
        fields_resp = await get_job_fields(job_id, tenant_id, db)

        return {
            **ingest_res,
            "processing_result": processing_result,
            "summary": summary,
            "fields": fields_resp,
        }
    # if auto_process is false just return ingestion info
    return ingest_res


@app.post("/upload/bulk", tags=["Ingress"])
async def upload_bulk_fax(
    files: List[UploadFile] = File(...),
    tenant_id: str = Form(default="default"),
    auto_process: bool = Form(default=False),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Upload multiple fax documents for processing under the same tenant.
    
    Workflow for EACH file:
    1. CLASSIFY document first (PyMuPDF + TinyOCR)
    2. Only ACCEPT and SAVE PA documents
    3. REJECT non-PA documents
    
    Files are ingested one by one and can optionally be queued for sequential processing.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    results = []
    accepted_ids: List[int] = []

    for index, upload_file in enumerate(files):
        temp_file_path = None
        try:
            # Step 1: Read file for classification
            content = await upload_file.read()
            if not content:
                results.append({
                    "filename": upload_file.filename or f"file_{index+1}",
                    "status": "rejected",
                    "error": "File is empty"
                })
                continue
            
            # Step 2: Save to temp file for classification
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                temp_file_path = tmp.name
                tmp.write(content)
            
            # Step 3: CLASSIFY FIRST (before saving to database)
            logger.info(f"Classifying bulk file {index+1}: {upload_file.filename}")
            
            try:
                classification_result = classify_document(temp_file_path)
                
                logger.info(
                    f"Bulk file classification result - Type: {classification_result.document_type}, "
                    f"Confidence: {classification_result.confidence:.2f}, "
                    f"Payer: {classification_result.matched_payer}"
                )
                
                # Step 4: REJECT if NOT PA or low confidence (lowered threshold from 0.70 to 0.60)
                if classification_result.document_type != "prior_authorization" or classification_result.confidence < 0.60:
                    logger.warning(
                        f"Bulk file rejected - Not a PA or low confidence: "
                        f"Type={classification_result.document_type}, "
                        f"Confidence={classification_result.confidence:.2f}"
                    )
                    
                    results.append({
                        "filename": upload_file.filename or f"file_{index+1}",
                        "status": "rejected",
                        "reason": f"Not a Prior Authorization document (Type: {classification_result.document_type}, Confidence: {classification_result.confidence:.0%})",
                        "classification": {
                            "document_type": classification_result.document_type,
                            "confidence": f"{classification_result.confidence:.0%}"
                        }
                    })
                    continue
                
                # Step 5: ACCEPT PA - Save to database with SHA
                logger.info(f"Bulk file accepted as PA - Proceeding with ingestion")
                
                # Ingest from bytes
                ingest_result = await _ingest_upload_file_from_bytes(
                    content,
                    upload_file.filename,
                    upload_file.content_type,
                    tenant_id,
                    db,
                    index
                )
                
                fax_job_id = ingest_result["fax_job_id"]
                accepted_ids.append(fax_job_id)
                
                # Add classification info to result
                ingest_result["classification"] = {
                    "document_type": classification_result.document_type,
                    "confidence": f"{classification_result.confidence:.0%}",
                    "detected_payer": classification_result.matched_payer
                }
                ingest_result["status"] = "accepted"
                
                results.append(ingest_result)
                logger.info(f"Bulk file ingested as FaxJob {fax_job_id}")
                
            except Exception as classify_error:
                logger.error(f"Classification error in bulk upload for file {index+1}: {classify_error}", exc_info=True)
                results.append({
                    "filename": upload_file.filename or f"file_{index+1}",
                    "status": "failed",
                    "error": f"Classification failed: {str(classify_error)}"
                })
        
        except HTTPException as exc:
            logger.warning("Bulk upload error for file %s: %s", upload_file.filename, exc.detail)
            results.append({
                "filename": upload_file.filename or f"file_{index+1}",
                "status": "failed",
                "error": exc.detail
            })
        except Exception as exc:
            logger.error("Bulk upload failed for file %s: %s", upload_file.filename, exc, exc_info=True)
            results.append({
                "filename": upload_file.filename or f"file_{index+1}",
                "status": "failed",
                "error": str(exc)
            })
        finally:
            # Clean up temp file
            if temp_file_path:
                Path(temp_file_path).unlink(missing_ok=True)

    if auto_process and accepted_ids:
        if background_tasks:
            background_tasks.add_task(_process_job_queue, accepted_ids, tenant_id)
        else:
            _process_job_queue(accepted_ids, tenant_id)

    response_body = {
        "tenant_id": tenant_id,
        "jobs": results,
        "accepted_count": len(accepted_ids),
        "rejected_count": len(results) - len(accepted_ids),
        "requested_count": len(files),
        "message": "Bulk upload processed"
    }

    status_code = 201 if accepted_ids else 400
    return JSONResponse(response_body, status_code=status_code)


@app.get("/jobs/{fax_job_id}", tags=["Ingress"])
async def get_fax_job(fax_job_id: int, db: Session = Depends(get_db)):
    """
    Get details of a specific fax job
    
    Args:
        fax_job_id: ID of the fax job
        db: Database session
        
    Returns:
        JSON with fax job details
    """
    fax_job = db.query(FaxJob).filter(FaxJob.id == fax_job_id).first()
    
    if not fax_job:
        raise HTTPException(status_code=404, detail="Fax job not found")
    
    return {
        "fax_job_id": fax_job.id,
        "tenant_id": fax_job.tenant_id,
        "sha256": fax_job.sha256,
        "status": fax_job.status,
        "created_at": fax_job.created_at.isoformat() if fax_job.created_at else None,
        "finalized_at": fax_job.finalized_at.isoformat() if fax_job.finalized_at else None,
        "review_needed": fax_job.review_needed
    }


@app.get("/jobs", tags=["Ingress"])
async def list_fax_jobs(
    tenant_id: str = None,
    status: str = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List fax jobs with optional filtering
    
    Args:
        tenant_id: Filter by tenant
        status: Filter by status
        limit: Maximum number of results
        offset: Number of results to skip
        db: Database session
        
    Returns:
        List of fax jobs
    """
    query = db.query(FaxJob)
    
    if tenant_id:
        query = query.filter(FaxJob.tenant_id == tenant_id)
    if status:
        query = query.filter(FaxJob.status == status)
    
    total = query.count()
    jobs = query.order_by(FaxJob.created_at.desc()).offset(offset).limit(limit).all()
    
    # Update review_needed for completed jobs if fields need review
    for job in jobs:
        if job.status in {"completed", "ocr_complete"}:
            review_required_fields = _collect_review_fields(db, job.id)
            review_required_count = len(review_required_fields)
            if review_required_count > 0 and not job.review_needed:
                job.review_needed = True
    
    db.commit()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": [
            {
                "fax_job_id": job.id,
                "tenant_id": job.tenant_id,
                "sha256": job.sha256,
                "status": job.status,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "review_needed": job.review_needed
            }
            for job in jobs
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)


# ============================================================================
# PROCESSING ENDPOINTS - OCR & Field Extraction
# ============================================================================


@app.post("/process/bulk", tags=["Processing"])
async def process_bulk_fax(
    payload: BulkProcessRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    job_ids = list(dict.fromkeys(payload.job_ids or []))
    tenant_id = payload.tenant_id or "default"

    if not job_ids:
        raise HTTPException(status_code=400, detail="Provide at least one job_id")

    valid_job_ids: List[int] = []
    skipped = []

    for job_id in job_ids:
        fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()

        if not fax_job:
            skipped.append({"job_id": job_id, "reason": "not_found"})
            continue

        if fax_job.tenant_id != tenant_id:
            skipped.append({"job_id": job_id, "reason": "tenant_mismatch"})
            continue

        valid_job_ids.append(job_id)

    if not valid_job_ids:
        raise HTTPException(status_code=404, detail="No jobs matched tenant or are missing")

    background_tasks.add_task(_process_job_queue, valid_job_ids, tenant_id)

    return {
        "tenant_id": tenant_id,
        "accepted_job_ids": valid_job_ids,
        "skipped": skipped,
        "mode": "sequential",
        "message": f"Queued {len(valid_job_ids)} job(s) for sequential processing"
    }

@app.post("/process/{job_id}", tags=["Processing"])
async def process_fax(
    job_id: int,
    background_tasks: BackgroundTasks,
    tenant_id: str = "default",
    db: Session = Depends(get_db)
):
    """
    🚀 **Process a fax document with OCR**
    
    This endpoint triggers the full processing pipeline:
    1. Retrieves job from database
    2. Loads file from storage
    3. Splits PDF into pages
    4. Preprocesses images (deskew, denoise, DPI normalization)
    5. Runs PaddleOCR to extract text with bounding boxes
    6. Saves OCR evidence files (tokens + coordinates + confidence scores)
    7. Updates job status
    
    **Parameters:**
    - **job_id**: Job ID from the upload endpoint
    - **tenant_id**: Tenant identifier (must match upload tenant)
    
    **Returns:** Processing status and job details
    """
    try:
        # Get job from database
        fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
        
        if not fax_job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        if fax_job.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Tenant mismatch")
        
        file_path = _resolve_job_file(job_id, tenant_id)
        logger.info(f"Found file for job {job_id}: {file_path}")
        
        # Update job status to processing
        fax_job.status = "processing"
        db.commit()
        
        # Trigger background processing
        background_tasks.add_task(
            _process_uploaded_file,
            job_id=job_id,
            tenant_id=tenant_id,
            file_path=file_path
        )
        
        return {
            "job_id": job_id,
            "status": "processing",
            "message": "Processing started in background",
            "tenant_id": tenant_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start processing: {str(e)}")


@app.get("/process/status/{job_id}", tags=["Processing"])
async def get_processing_status(job_id: int, tenant_id: str = "default", db: Session = Depends(get_db)):
    """
    📊 **Get processing status for a job**
    
    Returns the current status and processing details for a job.
    
    **Possible statuses:**
    - `ingested`: File uploaded, not yet processed
    - `processing`: Currently being processed
    - `preprocessed`: Pages split and cleaned
    - `ocr_complete`: OCR extraction complete with tokens & bounding boxes
    - `failed`: Processing encountered an error
    """
    try:
        fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
        
        if not fax_job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        if fax_job.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Tenant mismatch")
        
        # Check for output files
        job_storage = Path(f"fax_processing/storage/jobs/{tenant_id}/{job_id}")
        pages_dir = job_storage / "pages"
        ocr_dir = job_storage / "ocr_evidence"
        
        processed_pages = 0
        if pages_dir.exists():
            processed_pages = len(list(pages_dir.glob("page_*")))
        
        ocr_pages = 0
        if ocr_dir.exists():
            ocr_pages = len(list(ocr_dir.glob("page_*_ocr.json")))
        
        return {
            "job_id": fax_job.id,
            "tenant_id": fax_job.tenant_id,
            "status": fax_job.status,
            "total_pages": fax_job.total_pages or 0,
            "processed_pages": processed_pages,
            "ocr_pages": ocr_pages,
            "created_at": fax_job.created_at.isoformat() if fax_job.created_at else None,
            "finalized_at": fax_job.finalized_at.isoformat() if fax_job.finalized_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@app.get("/export-csv/{job_id}", tags=["Processing"])
async def export_csv(
    job_id: int,
    tenant_id: str = "default",
    db: Session = Depends(get_db)
):
    """
    📊 **Export extracted fields as CSV**
    
    Downloads a CSV file containing all extracted insurance fields for the job.
    Includes source information (LLM vs VLM) for each extracted field.
    
    **Parameters:**
    - **job_id**: Job ID to export
    - **tenant_id**: Tenant identifier
    
    **Returns:** CSV file download with columns: Field Name, Value, Method, Source, Confidence, Requires Review, Validation Errors, Validated
    """
    try:
        # Verify job exists and belongs to tenant
        fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
        if not fax_job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        if fax_job.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Tenant mismatch")

        # Get extracted fields
        from shared.models.fax_extracted_field import FaxExtractedField
        fields = db.query(FaxExtractedField).filter(FaxExtractedField.fax_job_id == job_id).all()

        if not fields:
            raise HTTPException(status_code=404, detail="No extracted fields found for this job")

        # Create CSV content
        import csv
        import io
        from fastapi.responses import StreamingResponse

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Field Name", "Value", "Method", "Source", "Confidence", "Requires Review", "Validation Errors", "Validated"
        ])

        # Write data
        for field in fields:
            # Determine source from method
            source = "LLM" if field.method and field.method.upper() == "LLM" else ("VLM" if field.method and field.method.upper() == "VLM" else "AI")
            
            # Get validation info
            requires_review = "Yes" if field.confidence and field.confidence < 0.8 else "No"
            validation_errors = field.evidence_text if field.evidence_text else ""
            
            writer.writerow([
                field.field_key.replace('_', ' ').title(),
                field.value,
                field.method or "ai",
                source,
                field.confidence or 0.9,
                requires_review,
                validation_errors,
                "Yes" if field.validated else "No"
            ])

        output.seek(0)
        csv_content = output.getvalue()
        output.close()

        # Return as downloadable CSV
        def generate():
            yield csv_content

        return StreamingResponse(
            generate(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=extracted_fields_job_{job_id}.csv"}
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export CSV: {str(e)}")
    
SUMMARY_KEY_FIELDS = [
    ("insurance_company_name", "Insurance company"),
    ("insurance_member_number", "Member number"),
    ("insurance_member_name", "Member name"),
    ("approval_status", "Approval status"),
    ("approval_number", "Approval number"),
    ("approved_service_cpt", "Approved CPT"),
    ("approved_units", "Approved units"),
    ("service_start_date", "Service start"),
    ("service_end_date", "Service end"),
    ("insurance_rep_name", "Rep name"),
    ("insurance_rep_contact", "Rep contact"),
    ("fax_received_date", "Fax received")
]

SUMMARY_FINAL_STATUSES = {"ocr_complete", "completed", "failed"}


def _fetch_horizontal_summary(db: Session, job_id: int):
    try:
        result = db.execute(
            text("SELECT * FROM extracted_fields_horizontal WHERE job_id = :job_id"),
            {"job_id": job_id}
        ).mappings().first()

        return dict(result) if result else None
    except Exception as exc:
        logger.debug("Unable to read horizontal summary for job %s: %s", job_id, exc)
        return None


def _format_field_label(field_key: str) -> str:
    return field_key.replace("_", " ").title()


def _requires_review(field: FaxExtractedField) -> bool:
    return isinstance(field.confidence, (float, int)) and field.confidence < 0.8


def _collect_review_fields(db: Session, job_id: int) -> List[str]:
    review_fields = []
    fields = db.query(FaxExtractedField).filter(FaxExtractedField.fax_job_id == job_id).all()
    for field in fields:
        if _requires_review(field):
            review_fields.append(_format_field_label(field.field_key))
    return review_fields


def _build_status_badge(
    status: str,
    review_needed: bool,
    has_modifications: bool,
    review_required_count: int,
):
    normalized_status = (status or "").lower()

    if review_required_count:
        plural = "" if review_required_count == 1 else "s"
        return (
            "⚠️",
            f"Agree-to-finalize mode: Review required for {review_required_count} field{plural}",
        )

    if normalized_status == "failed":
        return "⚠️", "Processing failed"
    if review_needed:
        return "⚠️", "Review required"
    if has_modifications:
        return "⚠️", "Human edits detected"
    if normalized_status in {"ocr_complete", "completed"}:
        return "✅", "Extraction ready"
    if normalized_status == "preprocessed":
        return "🟡", "Preprocessing complete"
    if normalized_status == "processing":
        return "⚙️", "Processing in progress"
    return "⌛", "Awaiting processing"


def _extract_key_fields(row_data: dict):
    key_fields = []
    for key, label in SUMMARY_KEY_FIELDS:
        value = row_data.get(key)
        if value is not None and value != "":
            key_fields.append({"label": label, "value": str(value)})
    return key_fields


@app.get("/jobs/{job_id}/summary", tags=["Processing"])
async def get_job_summary(
    job_id: int,
    tenant_id: str = "default",
    db: Session = Depends(get_db)
):
    fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
    if not fax_job:
        raise HTTPException(status_code=404, detail="Fax job not found")
    if fax_job.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")

    horizontal_row = _fetch_horizontal_summary(db, job_id) or {}
    status_value = horizontal_row.get("status") or fax_job.status or "ingested"
    review_needed = bool(horizontal_row.get("review_needed")) if "review_needed" in horizontal_row else bool(fax_job.review_needed)
    has_modifications = bool(horizontal_row.get("has_human_modifications")) if "has_human_modifications" in horizontal_row else bool(fax_job.has_human_modifications)
    modified_fields = horizontal_row.get("modified_fields") or fax_job.modified_fields
    created_at = horizontal_row.get("created_at") or fax_job.created_at
    finalized_at = horizontal_row.get("finalized_at") or fax_job.finalized_at

    review_required_fields = _collect_review_fields(db, job_id)
    review_required_count = len(review_required_fields)
    
    # Update review_needed if fields require review
    if review_required_count > 0 and not review_needed:
        fax_job.review_needed = True
        db.commit()
    
    status_icon, status_message = _build_status_badge(
        status_value,
        review_needed,
        has_modifications,
        review_required_count,
    )
    key_fields = _extract_key_fields(horizontal_row)
    is_final = (status_value or "").lower() in SUMMARY_FINAL_STATUSES

    return {
        "job_id": fax_job.id,
        "tenant_id": fax_job.tenant_id,
        "status": status_value,
        "status_icon": status_icon,
        "status_message": status_message,
        "is_final": is_final,
        "review_needed": review_needed,
        "has_human_modifications": has_modifications,
        "modified_fields": modified_fields,
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        "finalized_at": finalized_at.isoformat() if isinstance(finalized_at, datetime) else finalized_at,
        "total_pages": fax_job.total_pages,
        "key_fields": key_fields,
        "review_required_count": review_required_count,
        "review_required_fields": review_required_fields,
        "extracted_fields_available": bool(horizontal_row)
    }


@app.get("/jobs/{job_id}/fields", tags=["Processing"])
async def get_job_fields(
    job_id: int,
    tenant_id: str = "default",
    db: Session = Depends(get_db)
):
    fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
    if not fax_job:
        raise HTTPException(status_code=404, detail="Fax job not found")
    if fax_job.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")

    horizontal_row = _fetch_horizontal_summary(db, job_id)
    if not horizontal_row:
        return {"job_id": fax_job.id, "tenant_id": fax_job.tenant_id, "fields": {}, "message": "No extracted fields yet"}

    # Remove metadata columns from the field map
    field_payload = {
        key: value
        for key, value in horizontal_row.items()
        if key not in {"job_id", "tenant_id", "status", "created_at", "finalized_at", "review_needed", "has_human_modifications", "modified_fields"}
        and value is not None
    }

    return {
        "job_id": fax_job.id,
        "tenant_id": fax_job.tenant_id,
        "status": horizontal_row.get("status") or fax_job.status,
        "fields": field_payload
    }


def _process_job_queue(job_ids: List[int], tenant_id: str):
    for job_id in job_ids:
        try:
            file_path = _resolve_job_file(job_id, tenant_id)
        except HTTPException as exc:
            logger.error("Job %s skipped: %s", job_id, exc.detail)
            continue

        _process_uploaded_file(job_id=job_id, tenant_id=tenant_id, file_path=file_path)


# Background processing function
def _process_uploaded_file(job_id: int, tenant_id: str, file_path: Path):
    """Run the local OCR and extraction pipeline for an uploaded job."""
    file_path = Path(file_path).resolve()
    logger.info("Starting local processing for job %s", job_id)
    logger.info("File: %s", file_path)

    db = SessionLocal()
    try:
        fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
        if not fax_job:
            raise RuntimeError(f"Job {job_id} not found")
        fax_job.status = "processing"
        db.commit()
    finally:
        db.close()

    try:
        from fax_processing.core.preprocessing import preprocessor
        from fax_processing.core.ocr_engine import ocr_engine
        from fax_processing.core.storage import storage

        total_pages = preprocessor.process_document(str(job_id), tenant_id, file_path)

        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "preprocessed"
                fax_job.total_pages = total_pages
                db.commit()
        finally:
            db.close()

        ocr_texts = []
        page_images = []
        for page_num in range(1, total_pages + 1):
            page_image_path = storage._get_page_dir(str(job_id), tenant_id, page_num) / f"page_{page_num:04d}.png"
            if not page_image_path.exists():
                logger.warning("Page image not found for job %s page %s: %s", job_id, page_num, page_image_path)
                continue

            page_metadata = ocr_engine.process_page(
                job_id=str(job_id),
                tenant_id=tenant_id,
                page_num=page_num,
                page_image_path=page_image_path,
            )
            page_text = " ".join(token.text for token in page_metadata.ocr_tokens)
            ocr_texts.append(page_text)
            page_images.append(str(page_image_path))

        extracted_fields = _extract_fields_locally(job_id, ocr_texts, page_images)
        review_needed = _save_local_extraction(job_id, extracted_fields)

        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "completed"
                fax_job.review_needed = review_needed
                fax_job.finalized_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

        logger.info("Local processing completed for job %s", job_id)
        return {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "status": "completed",
            "total_pages": total_pages,
            "fields_saved": len(extracted_fields),
            "review_needed": review_needed,
        }
    except Exception as exc:
        logger.error("Local processing failed for job %s: %s", job_id, exc, exc_info=True)
        db = SessionLocal()
        try:
            fax_job = db.query(FaxJob).filter(FaxJob.id == job_id).first()
            if fax_job:
                fax_job.status = "failed"
                db.commit()
        finally:
            db.close()
        raise


def _extract_fields_locally(job_id: int, ocr_texts: List[str], page_images: List[str]):
    try:
        from fax_processing.core.hybrid_field_extractor import HybridFieldExtractor

        extractor = HybridFieldExtractor()
        return extractor.extract_fields(job_id=job_id, ocr_texts=ocr_texts, page_images=page_images)
    except Exception as exc:
        logger.warning("Hybrid extraction failed for job %s, using basic extractor: %s", job_id, exc, exc_info=True)
        from fax_processing.core.field_extractor import field_extractor

        return field_extractor.extract_fields(job_id=job_id, ocr_texts=ocr_texts, page_images=page_images)


def _save_local_extraction(job_id: int, extracted_fields: dict) -> bool:
    review_needed = False
    critical_fields = {"insurance_member_name", "approval_status", "insurance_member_number"}
    db = SessionLocal()
    try:
        for field_key, field_data in (extracted_fields or {}).items():
            if not isinstance(field_data, dict):
                continue

            field_value = field_data.get("value") or ""
            confidence = field_data.get("confidence") or 0.0
            source = field_data.get("source") or field_data.get("method") or "AI"
            if confidence < 0.8:
                review_needed = True

            existing = db.query(FaxExtractedField).filter(
                FaxExtractedField.fax_job_id == job_id,
                FaxExtractedField.field_key == field_key,
            ).first()
            if existing:
                existing.value = field_value
                existing.confidence = confidence
                existing.method = str(source).upper()
                existing.evidence_text = "Extracted by local processing pipeline"
                existing.validated = True
                existing.original_ai_value = field_data.get("original_ai_value") or field_value
            else:
                db.add(FaxExtractedField(
                    fax_job_id=job_id,
                    field_key=field_key,
                    value=field_value,
                    confidence=confidence,
                    method=str(source).upper(),
                    evidence_text="Extracted by local processing pipeline",
                    validated=True,
                    human_modified=False,
                    original_ai_value=field_data.get("original_ai_value") or field_value,
                ))

        for field_key in critical_fields:
            field_data = (extracted_fields or {}).get(field_key)
            if not isinstance(field_data, dict) or not field_data.get("value"):
                review_needed = True

        db.commit()
        return review_needed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

