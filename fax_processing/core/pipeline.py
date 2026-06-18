"""
Pipeline orchestrator - coordinates ingestion -> preprocessing -> OCR
"""
import logging
from pathlib import Path

from fax_processing.core.storage import storage
from fax_processing.core.preprocessing import preprocessor
from fax_processing.core.ocr_engine import ocr_engine
from fax_processing.core.field_extractor import field_extractor
from fax_processing.models.schemas import JobStatus

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates the end-to-end processing pipeline"""
    
    async def process_job(self, job_id: str, tenant_id: str):
        """
        Process a job through the pipeline:
        1. Load job metadata
        2. Split document into pages & preprocess
        3. Run OCR on each page with evidence
        4. Update job status
        """
        try:
            logger.info(f"Starting pipeline for job {job_id}")
            
            # Load job
            job = storage.load_job_metadata(job_id, tenant_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return
            
            # Update status to PROCESSING
            storage.update_job_status(job_id, tenant_id, JobStatus.PROCESSING)
            
            # Get original file path
            job_dir = storage._get_job_dir(job_id, tenant_id)
            original_files = list((job_dir / "original").glob("*"))
            
            if not original_files:
                raise Exception("Original file not found")
            
            original_file = original_files[0]
            
            # Step 1: Preprocess & split pages
            logger.info(f"Preprocessing document for job {job_id}")
            total_pages = preprocessor.process_document(job_id, tenant_id, original_file)
            
            # Update job with total pages
            job.total_pages = total_pages
            storage.save_job_metadata(job)
            
            logger.info(f"Document split into {total_pages} pages")
            
            # Step 2: Run OCR on each page
            logger.info(f"Running OCR on {total_pages} pages")
            
            for page_num in range(1, total_pages + 1):
                # Get page image path
                page_dir = storage._get_page_dir(job_id, tenant_id, page_num)
                page_files = list(page_dir.glob("page_*.png"))
                
                if not page_files:
                    logger.warning(f"Page {page_num} image not found, skipping")
                    continue
                
                page_image_path = page_files[0]
                
                # Run OCR
                logger.info(f"Processing page {page_num}/{total_pages}")
                page_meta = ocr_engine.process_page(
                    job_id, tenant_id, page_num, page_image_path
                )
                
                logger.info(f"Page {page_num}: extracted {len(page_meta.ocr_tokens)} tokens")
            
            # Step 3: Extract fields using AI
            logger.info(f"Extracting fields for job {job_id}")
            
            # Collect OCR texts and page images for field extraction
            ocr_texts = []
            page_images = []
            
            for page_num in range(1, total_pages + 1):
                # Load OCR results
                page_dir = storage._get_page_dir(job_id, tenant_id, page_num)
                ocr_file = page_dir / "ocr_results.json"
                
                if ocr_file.exists():
                    import json
                    with open(ocr_file, 'r') as f:
                        ocr_data = json.load(f)
                        ocr_texts.append(ocr_data.get('text', ''))
                        
                        # Get page image path for VLM
                        page_files = list(page_dir.glob("page_*.png"))
                        if page_files:
                            page_images.append(str(page_files[0]))
            
            # Extract fields
            extracted_fields = field_extractor.extract_fields(
                job_id=int(job_id),
                ocr_texts=ocr_texts,
                page_images=page_images
            )
            
            logger.info(f"Extracted {len(extracted_fields)} fields")
            
            # Save extracted fields to database
            self._save_extracted_fields(job_id, tenant_id, extracted_fields)
            
            # Update status to COMPLETED
            storage.update_job_status(job_id, tenant_id, JobStatus.COMPLETED)
            
            # Update status to COMPLETED
            storage.update_job_status(job_id, tenant_id, JobStatus.COMPLETED)
            
            logger.info(f"Pipeline completed for job {job_id}")
        
        except Exception as e:
            logger.error(f"Pipeline failed for job {job_id}: {str(e)}", exc_info=True)
            storage.update_job_status(
                job_id, tenant_id, 
                JobStatus.FAILED, 
                error_message=str(e)
            )
    
    def _save_extracted_fields(self, job_id: str, tenant_id: str, extracted_fields: dict):
        """Save extracted fields to database and determine if human review is needed"""
        from shared.database import SessionLocal
        from shared.models.fax_extracted_field import FaxExtractedField
        from shared.models.fax_job import FaxJob
        
        db = SessionLocal()
        try:
            low_confidence_count = 0
            
            for field_key, field_data in extracted_fields.items():
                value = field_data.get('value', '')
                confidence = field_data.get('confidence', 0.0)
                source = field_data.get('source', 'unknown')
                
                # Create extracted field record
                extracted_field = FaxExtractedField(
                    fax_job_id=int(job_id),
                    field_key=field_key,
                    value=value,
                    confidence=confidence,
                    method=source.upper()
                )
                
                db.add(extracted_field)
                
                # Count low confidence fields
                if confidence < 0.8:
                    low_confidence_count += 1
            
            # Mark job as needing review if there are low confidence fields
            fax_job = db.query(FaxJob).filter(FaxJob.id == int(job_id)).first()
            if fax_job:
                fax_job.review_needed = low_confidence_count > 0
                logger.info(f"Job {job_id}: {low_confidence_count} fields need review")
            
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to save extracted fields for job {job_id}: {e}")
            db.rollback()
        finally:
            db.close()


# Singleton instance
pipeline_orchestrator = PipelineOrchestrator()
