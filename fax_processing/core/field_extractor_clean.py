"""
Hybrid Regex + LLM Field Extraction for Insurance Fax Processing
Phase 1: Fast regex extraction, Phase 2: LLM validation/correction, Phase 3: VLM gap-filling
Integrated with validation engine for quality assurance
"""
import os
import json
import base64
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

from fax_processing.core.validation_engine import validation_engine
from fax_processing.core.hybrid_field_extractor import HybridFieldExtractor
from shared.database import SessionLocal
from shared.models.fax_extracted_field import FaxExtractedField

# Load environment variables
load_dotenv()


class AIFieldExtractor:
    """Hybrid regex + LLM field extraction with VLM gap-filling"""

    def __init__(self):
        # Use the hybrid extractor
        self.hybrid_extractor = HybridFieldExtractor()

        # Keep backward compatibility
        self.field_definitions = self.hybrid_extractor.field_definitions
        self.critical_fields = self.hybrid_extractor.critical_fields

    def extract_fields(self, job_id: int, ocr_texts: List[str], page_images: List[str] = None) -> Dict[str, Dict[str, str]]:
        """
        Extract fields using hybrid regex + LLM approach with VLM gap-filling

        Args:
            job_id: Fax job ID
            ocr_texts: List of OCR text strings from all pages
            page_images: List of paths to page images for VLM gap-filling

        Returns:
            Dict of field_name -> {'value': str, 'source': 'regex'|'llm'|'vlm', 'confidence': float}
        """
        print(f"🚀 Starting hybrid extraction for job {job_id}")

        # Use the hybrid extractor
        extracted_fields = self.hybrid_extractor.extract_fields(job_id, ocr_texts, page_images)

        # Save to database
        self._save_extracted_fields(job_id, extracted_fields)

        return extracted_fields

    def _save_extracted_fields(self, job_id: int, fields: Dict[str, Dict[str, str]]):
        """Save extracted fields to database"""
        db = SessionLocal()
        try:
            for field_key, field_data in fields.items():
                value = field_data.get('value', '')
                source = field_data.get('source', 'unknown')
                confidence = field_data.get('confidence', 0.0)

                # Create or update field record
                field_record = db.query(FaxExtractedField).filter(
                    FaxExtractedField.fax_job_id == job_id,
                    FaxExtractedField.field_key == field_key
                ).first()

                if field_record:
                    # Update existing
                    field_record.value = value
                    field_record.method = f"HYBRID_{source.upper()}"
                    field_record.confidence = confidence
                else:
                    # Create new
                    field_record = FaxExtractedField(
                        fax_job_id=job_id,
                        field_key=field_key,
                        value=value,
                        method=f"HYBRID_{source.upper()}",
                        confidence=confidence
                    )
                    db.add(field_record)

            db.commit()
            print(f"✅ Saved {len(fields)} fields for job {job_id}")

        except Exception as e:
            db.rollback()
            print(f"❌ Failed to save fields for job {job_id}: {e}")
        finally:
            db.close()

    # Keep backward compatibility methods
    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode image to base64 for OpenAI Vision API"""
        return self.hybrid_extractor._ask_openai_vision.__globals__['base64'].b64encode(
            open(image_path, "rb").read()
        ).decode('utf-8')

    def _calculate_confidence(self, field_key: str, value: str, source: str) -> float:
        """Calculate confidence score for extracted field"""
        return self.hybrid_extractor._calculate_confidence(field_key, value, source)

    def _verify_with_vlm(self, fields: Dict[str, Dict[str, str]], page_images: List[str]) -> Dict[str, Dict[str, str]]:
        """Legacy method - now handled by hybrid extractor"""
        return self.hybrid_extractor._gap_fill_with_vlm(fields, page_images)

    def _apply_validation_engine(self, fields: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """Apply validation and canonicalization engine"""
        return self.hybrid_extractor._apply_validation_engine(fields)

    def _get_display_name(self, field_key: str) -> str:
        """Convert field key to display name"""
        name_map = {
            'insurance_company_name': 'Insurance Company Name',
            'insurance_member_number': 'Insurance Member #',
            'insurance_member_name': 'Insurance Member Name',
            'approval_status': 'Approval Status',
            'approval_number': 'Approval Number',
            'approved_service_cpt': 'Approved Service/CPT Code',
            'approved_units': 'Approved Units',
            'service_start_date': 'Service Start Date',
            'service_end_date': 'Service End Date',
            'insurance_rep_name': 'Insurance Rep Name',
            'insurance_rep_contact': 'Insurance Rep Contact',
            'fax_received_date': 'Fax Received Date',
        }
        return name_map.get(field_key, field_key.replace('_', ' ').title())


# Singleton instance
field_extractor = AIFieldExtractor()