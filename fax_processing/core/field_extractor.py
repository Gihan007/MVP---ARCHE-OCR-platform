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
    def build_llm_prompt(self, field_key, field_data, ocr_text):
        prompt = f"Extract the value for the field '{field_key}' from the following OCR text:\n\n{ocr_text}\n"
        user_note = field_data.get('user_note')
        if user_note:
            prompt += (
                "\nIMPORTANT: Before extracting, please read and follow this instruction for this field:\n"
                f"{user_note}\n"
            )
        return prompt
    def _load_field_notes(self):
        """Load user notes for fields from review_notes.txt (field only, no page)"""
        import os
        notes_path = os.path.join(os.path.dirname(__file__), '../../fax_ingress/review_notes.txt')
        notes_dict = {}
        if os.path.exists(notes_path):
            with open(notes_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        # Example: Field approved_units, Page 1: always use capital letters
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            meta, note = parts
                            if meta.startswith('Field '):
                                field = meta.replace('Field ', '').split(',')[0].strip()
                                notes_dict[field] = note.strip()
        return notes_dict

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

        # Load user notes for fields
        field_notes = self._load_field_notes()

        # Use the hybrid extractor, passing notes for LLM context
        # Patch: inject notes into LLM validation
        if hasattr(self.hybrid_extractor, '_validate_with_llm'):
            orig_validate_with_llm = self.hybrid_extractor._validate_with_llm
            def validate_with_llm_with_notes(regex_candidates, full_text, field_notes=field_notes):
                return orig_validate_with_llm(regex_candidates, full_text, field_notes)
            self.hybrid_extractor._validate_with_llm = validate_with_llm_with_notes
        extracted_fields = self.hybrid_extractor.extract_fields(job_id, ocr_texts, page_images)

        # Attach note to each field if available
        for field_key, field_data in extracted_fields.items():
            note = field_notes.get(field_key)
            if note:
                field_data['user_note'] = note

        # Save to database
        self._save_extracted_fields(job_id, extracted_fields)

        return extracted_fields

    def save_extracted_fields(self, job_id: int, fields: Dict[str, Dict[str, str]], tenant_id: str = None):
        """Public method to save extracted fields to database"""
        self._save_extracted_fields(job_id, fields)

    def _save_extracted_fields(self, job_id: int, fields: Dict[str, Dict[str, str]]):
        """Save extracted fields to database with full metadata"""
        db = SessionLocal()
        try:
            for field_key, field_data in fields.items():
                value = field_data.get('value', '')
                source = field_data.get('source', 'unknown')
                confidence = field_data.get('confidence', 0.0)
                
                # Extract additional metadata for transparency
                llm_confidence = field_data.get('llm_confidence', 0.0)
                regex_confidence = field_data.get('regex_confidence', 0.0)
                agreement = field_data.get('agreement', 'NO_COMPARISON')
                reason = field_data.get('reason', 'standard')
                
                # Create metadata JSON for context
                metadata = {
                    'llm_confidence': llm_confidence,
                    'regex_confidence': regex_confidence,
                    'agreement': agreement,
                    'reason': reason,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                # Add optional blend info
                if 'blend_formula' in field_data:
                    metadata['blend_formula'] = field_data['blend_formula']
                if 'agreement_boost' in field_data:
                    metadata['agreement_boost'] = field_data['agreement_boost']

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