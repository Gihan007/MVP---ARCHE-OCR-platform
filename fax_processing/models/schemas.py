"""
Data models and schemas for fax processing
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class JobStatus(str, Enum):
    """Job processing status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    PREPROCESSED = "preprocessed"
    OCR_COMPLETE = "ocr_complete"
    COMPLETED = "completed"
    FAILED = "failed"


class BoundingBox(BaseModel):
    """Bounding box coordinates for OCR tokens"""
    x1: float
    y1: float
    x2: float
    y2: float
    x3: float
    y3: float
    x4: float
    y4: float


class OCRToken(BaseModel):
    """OCR token with text, confidence, and bounding box"""
    text: str
    confidence: float
    bbox: BoundingBox
    page_num: int


class PageMetadata(BaseModel):
    """Metadata for a processed page"""
    page_id: str
    page_num: int
    job_id: int
    width: int
    height: int
    dpi: int
    file_path: str
    ocr_tokens: List[OCRToken]


class FaxIngestRequest(BaseModel):
    """Request model for fax ingestion"""
    tenant_id: str = "default"
    auto_process: bool = False


class ProcessRequest(BaseModel):
    """Request model for fax processing"""
    tenant_id: str = "default"


class ProcessResponse(BaseModel):
    """Response model for fax processing"""
    job_id: int
    status: str
    message: str
    tenant_id: str


class ProcessLogResponse(BaseModel):
    """Response model for job processing logs"""
    job_id: int
    tenant_id: str
    status: Optional[str] = None
    entries: List[str] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    """Response model for job status queries"""
    job_id: int
    status: str
    total_pages: Optional[int] = None
    processed_pages: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    error_message: Optional[str] = None