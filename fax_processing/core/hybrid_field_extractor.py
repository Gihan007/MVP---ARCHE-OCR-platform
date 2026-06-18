"""
Regex + LLM Hybrid Field Extraction for Insurance Fax Processing
Phase 1: Fast regex extraction, Phase 2: LLM validation/correction, Phase 3: VLM gap-filling
"""
import re
import os
import json
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

from shared.config.settings import settings

from fax_processing.core.validation_engine import validation_engine
from shared.database import SessionLocal
from shared.models.fax_extracted_field import FaxExtractedField

# Load environment variables
load_dotenv()


class HybridFieldExtractor:
    """Hybrid regex + LLM field extraction with VLM gap-filling"""

    def __init__(self):
        self.client = None  # Lazy initialization
        self.llm_model = "gpt-4o-mini"  # For validation/correction
        self.vision_model = "gpt-4o"  # For final gap-filling
        self.vlm_backend = os.getenv("VLM_BACKEND", settings.vlm_backend).lower()
        self.vlm_model_path = settings.vlm_model_path

        # Common false positives to filter out
        self.false_positive_filters = {
            "insurance_member_number": [
                "ADMINISTRATION", "MEMBER", "INFORMATION", "REFERENCE", "AUTHORIZATION",
                "APPROVAL", "COVERAGE", "POLICY", "CLAIMS", "PATIENT", "SUBSCRIBER",
                "DEPENDENT", "BENEFITS", "SERVICES", "DOCUMENT", "REQUEST", "FORM",
                "PRIOR", "AUTH", "PRECERTIFICATION", "PREDETERMINATION"
            ],
            "approval_number": [
                "AUTHORIZATION", "APPROVAL", "PRIOR", "AUTH", "REFERENCE",
                "CLAIM", "DOCUMENT", "REQUEST", "NUMBER", "REQUIRED", "APPROVAL"
            ]
        }

        # Regex patterns for different field types - IMPROVED
        self.regex_patterns = {
            "insurance_member_number": [
                # Context-aware: Look for "Member ID:" or "Policy #:" patterns first
                r'(?:Member\s*(?:ID|Number|#)?|Subscriber\s*(?:ID|Number)|Policy\s*(?:#|Number))\s*[:=]?\s*([A-Z0-9]{6,20})',
                # Strong patterns: High confidence
                r'\b[A-Z]{1,3}\d{8,12}\b',  # Like "XYZ12345678" (letter prefix + 8+ digits)
                r'\b\d{3}[-]?\d{3}[-]?\d{4,6}\b',  # Like "123-456-7890" or similar
                # Weak patterns: Lower confidence (will be filtered)
                r'\b\d{8,12}\b',  # 8-12 digits only
                r'\b[A-Z0-9]{8,15}\b',  # Alphanumeric (CAREFUL: catches headers)
            ],
            "approval_number": [
                # Context-aware first
                r'(?:Authorization\s*(?:Number|#)|Approval\s*(?:Number|#)|Auth\s*#?|Ref(?:erence)?\s*#?)\s*[:=]?\s*([A-Z0-9]{6,20})',
                # Strong patterns
                r'\b[A-Z]{1,4}\d{8,12}\b',  # Like "AUTH12345678"
                r'\b\d{10,15}\b',  # Long numbers
                # Weak patterns
                r'\b\d{8,15}\b',  # Long numbers
                r'\b\d{4,6}[A-Z]\d{0,6}\b',  # Mixed format
            ],
            "insurance_member_name": [
                r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # First Last
                r'\b[A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+\b',  # First M. Last
                r'\b[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+\b',  # First Middle Last
            ],
            "insurance_company_name": [
                r'\b(?:Aetna|Blue Cross|Blue Shield|United Healthcare|Cigna|Humana|Anthem|Kaiser|Medicare|Medicaid)\b',
                r'\b[A-Z][a-zA-Z\s&]{3,30}(?:Insurance|Health|Medical|Care|Plan)\b',
            ],
            "approval_status": [
                r'\b(?:Approved|Denied|Pending|Approved with Conditions|Partially Approved)\b',
                r'\b(?:AUTH|DENIED|APPROVED|PENDING)\b',
            ],
            "approved_service_cpt": [
                r'\b\d{4,5}[A-Z]?\b',  # CPT codes
                r'\b[0-9]{4,5}(?:F|T|U)?\b',  # HCPCS codes
            ],
            "approved_units": [
                r'\b\d{1,3}\b',  # Small numbers for units
            ],
            "service_start_date": [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # MM/DD/YYYY or M/D/YY
                r'\b\d{2,4}[/-]\d{1,2}[/-]\d{1,2}\b',  # YYYY/MM/DD
            ],
            "service_end_date": [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # Same as start date
                r'\b\d{2,4}[/-]\d{1,2}[/-]\d{1,2}\b',
            ],
            "insurance_rep_name": [
                r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # First Last (similar to member name)
            ],
            "insurance_rep_contact": [
                r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',  # Phone numbers
                r'\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b',
            ],
            "fax_received_date": [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # Same date patterns
            ],
        }

        # Field priorities for regex matching (higher = more specific patterns)
        self.field_priorities = {
            "insurance_member_number": 3,
            "approval_number": 3,
            "insurance_member_name": 2,
            "insurance_company_name": 2,
            "approval_status": 2,
            "approved_service_cpt": 2,
            "service_start_date": 1,
            "service_end_date": 1,
            "insurance_rep_contact": 1,
            "fax_received_date": 1,
            "approved_units": 1,
            "insurance_rep_name": 1,
        }

        # Critical fields that need LLM validation
        self.critical_fields = [
            "insurance_member_name",
            "approval_status",
            "insurance_member_number",
            "approval_number"
        ]

        # Confidence thresholds for decision-making
        self.REGEX_CONFIDENCE_THRESHOLD = 0.80  # If regex >= 85%, trust it
        self.LLM_CONFIDENCE_THRESHOLD = 0.80    # If LLM >= 80%, use it
        self.VLM_CONFIDENCE_THRESHOLD = 0.70    # If VLM >= 70%, use it

        print("✅ Hybrid Regex + LLM extractor initialized")
        if self.vlm_backend == "donut":
            print(f"✅ Donut VLM backend selected (model: {self.vlm_model_path})")
        else:
            print("✅ OpenAI Vision backend selected for gap-filling")
        print(f"   Confidence thresholds: Regex={self.REGEX_CONFIDENCE_THRESHOLD}, LLM={self.LLM_CONFIDENCE_THRESHOLD}, VLM={self.VLM_CONFIDENCE_THRESHOLD}")

    def extract_fields(self, job_id: int, ocr_texts: List[str], page_images: List[str] = None) -> Dict[str, Dict[str, str]]:
        """
        Hybrid extraction with confidence-based source selection:
        - Regex first (fast)
        - LLM validation (flexible)
        - Smart selection: Use regex if high confidence, otherwise use LLM
        - VLM gap-filling for remaining empty fields

        Args:
            job_id: Fax job ID
            ocr_texts: List of OCR text strings from all pages
            page_images: List of paths to page images for VLM gap-filling

        Returns:
            Dict of field_name -> {'value': str, 'source': 'regex'|'llm'|'vlm', 'confidence': float}
        """
        # Combine all OCR text
        full_text = '\n\n'.join(ocr_texts)

        # Phase 1: Fast regex extraction
        print("🔍 Phase 1: Regex extraction...")
        regex_fields = self._extract_with_regex(full_text)

        # Phase 2: LLM validation and gap-filling
        print("🤖 Phase 2: LLM validation...")
        llm_fields = self._validate_with_llm(regex_fields, full_text)

        # Phase 3: Smart selection - choose between regex and LLM based on confidence
        print("🧠 Phase 3: Confidence-based selection (Regex vs LLM)...")
        selected_fields = self._select_best_fields(regex_fields, llm_fields)

        # Phase 4: VLM gap-filling for remaining empty fields
        if page_images:
            print("👁️ Phase 4: VLM gap-filling...")
            selected_fields = self._gap_fill_with_vlm(selected_fields, page_images)

        # Apply validation engine
        final_fields = self._apply_validation_engine(selected_fields)

        return final_fields

    def _select_best_fields(self, regex_fields: Dict[str, List[str]], llm_fields: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """
        Intelligent field selection with Confidence Blending + Agreement Boosting
        
        Strategy (Priority Order):
        1. NAME fields: Always use LLM if available (names have privacy sensitivity)
        2. High Regex Confidence (≥85%): Use regex if agreement detected (+15% boost)
        3. LLM Results: Use if LLM confidence is reasonable (0.75+)
        4. Agreement Boosting: +15% when regex/LLM agree, -20% when they disagree
        5. Confidence Blending: 70% LLM + 30% Regex when both available
        
        Args:
            regex_fields: Dict of field_name -> list of candidates (from regex)
            llm_fields: Dict of field_name -> {'value': str, 'confidence': float, 'llm_confidence': float}
        
        Returns:
            Dict with enhanced metadata: value, source, confidence, agreement, blend_info
        """
        best_fields = {}
        name_fields = ["insurance_member_name", "insurance_rep_name"]
        
        for field_key in self.regex_patterns.keys():
            llm_result = llm_fields.get(field_key, {})
            regex_candidates = regex_fields.get(field_key, [])
            
            # Get basic confidence scores
            regex_confidence = self._calculate_regex_confidence(field_key, regex_candidates)
            llm_confidence = llm_result.get('llm_confidence', 0.0)
            
            # === PRIORITY 1: NAME FIELDS ===
            if field_key in name_fields:
                if llm_result.get('value'):
                    best_fields[field_key] = {
                        'value': llm_result['value'],
                        'source': 'llm',
                        'confidence': llm_confidence,
                        'reason': 'name_priority',
                        'llm_confidence': llm_confidence,
                        'regex_confidence': regex_confidence,
                        'agreement': self._detect_agreement(llm_result.get('value'), regex_candidates)
                    }
                    print(f"  🤖 {field_key}: LLM (NAME PRIORITY, conf: {llm_confidence:.2f})")
                else:
                    print(f"  ⏳ {field_key}: EMPTY → VLM will attempt (name field)")
                continue
            
            # === PRIORITY 2: AGREEMENT BOOSTING ===
            # Check if regex and LLM agree
            agreement_type = self._detect_agreement(
                llm_result.get('value'),
                regex_candidates
            )
            
            # Apply agreement boost/penalty
            agreement_boost = 0.0
            if agreement_type == 'FULL_MATCH':
                agreement_boost = 0.15  # +15% when they fully agree
            elif agreement_type == 'DISAGREEMENT':
                agreement_boost = -0.20  # -20% when they disagree (uncertain)
            
            # === PRIORITY 3: CONFIDENCE BLENDING ===
            # If both sources available: blend them (70% LLM + 30% Regex)
            if regex_candidates and llm_result.get('value'):
                blended_confidence = (llm_confidence * 0.7) + (regex_confidence * 0.3)
                blended_confidence += agreement_boost
                blended_confidence = max(0.0, min(1.0, blended_confidence))
                
                # Prefer LLM when both available (more comprehensive)
                best_fields[field_key] = {
                    'value': llm_result['value'],
                    'source': 'llm',
                    'confidence': blended_confidence,
                    'reason': 'confidence_blend',
                    'llm_confidence': llm_confidence,
                    'regex_confidence': regex_confidence,
                    'agreement': agreement_type,
                    'agreement_boost': agreement_boost,
                    'blend_formula': '70% LLM + 30% Regex'
                }
                print(f"  🔀 {field_key}: BLENDED (LLM:{llm_confidence:.2f} + REGEX:{regex_confidence:.2f} = {blended_confidence:.2f}, {agreement_type})")
            
            # === PRIORITY 4: HIGH REGEX CONFIDENCE ===
            elif regex_confidence >= self.REGEX_CONFIDENCE_THRESHOLD and regex_candidates:
                final_confidence = regex_confidence + agreement_boost
                final_confidence = max(0.0, min(1.0, final_confidence))
                
                best_fields[field_key] = {
                    'value': regex_candidates[0],
                    'source': 'regex',
                    'confidence': final_confidence,
                    'reason': 'high_regex_confidence',
                    'llm_confidence': llm_confidence,
                    'regex_confidence': regex_confidence,
                    'agreement': agreement_type
                }
                print(f"  ✅ {field_key}: REGEX (HIGH: {final_confidence:.2f})")
            
            # === PRIORITY 5: LLM RESULT ===
            elif llm_result.get('value') and llm_confidence >= 0.65:
                final_confidence = llm_confidence + agreement_boost
                final_confidence = max(0.0, min(1.0, final_confidence))
                
                best_fields[field_key] = {
                    'value': llm_result['value'],
                    'source': 'llm',
                    'confidence': final_confidence,
                    'reason': 'llm_fallback',
                    'llm_confidence': llm_confidence,
                    'regex_confidence': regex_confidence,
                    'agreement': agreement_type
                }
                print(f"  🤖 {field_key}: LLM (confidence: {final_confidence:.2f})")
            
            # === FALLBACK: EMPTY (VLM gap-fill) ===
            else:
                print(f"  ⏳ {field_key}: EMPTY → VLM will attempt")
        
        return best_fields

    def _detect_agreement(self, llm_value: str, regex_candidates: List[str]) -> str:
        """
        Detect if LLM and Regex extraction methods agree
        
        Returns:
            'FULL_MATCH': Same value
            'PARTIAL_MATCH': One is substring of other
            'DISAGREEMENT': Different values (both non-empty)
            'NO_COMPARISON': One or both empty
        """
        if not llm_value or not regex_candidates:
            return 'NO_COMPARISON'
        
        llm_value = str(llm_value).strip().upper()
        
        for regex_val in regex_candidates:
            regex_val = str(regex_val).strip().upper()
            
            # Full match
            if llm_value == regex_val:
                return 'FULL_MATCH'
            
            # Partial match (one is substring)
            if llm_value in regex_val or regex_val in llm_value:
                return 'PARTIAL_MATCH'
        
        # Both have values but different → disagreement
        return 'DISAGREEMENT'

    def _calculate_regex_confidence(self, field_key: str, regex_candidates: List[str]) -> float:
        """
        Calculate confidence for regex extraction based on field type and matches
        
        Lower confidence for ambiguous patterns so LLM takes over when uncertain.
        """
        if not regex_candidates:
            return 0.0
        
        first_candidate = regex_candidates[0]
        
        # Base confidence by field type
        field_type_confidence = {
            # High confidence fields (specific patterns with labels)
            "approval_number": 0.90,
            "insurance_member_number": 0.88,
            "approved_service_cpt": 0.85,
            
            # Medium confidence
            "approved_units": 0.75,
            "insurance_company_name": 0.75,
            "approval_status": 0.80,
            "insurance_rep_contact": 0.82,
            "service_start_date": 0.78,
            "service_end_date": 0.78,
            
            # Lower confidence (names are ambiguous)
            "insurance_member_name": 0.65,
            "insurance_rep_name": 0.65,
            "fax_received_date": 0.72,
        }.get(field_key, 0.60)
        
        # Adjust based on candidate characteristics
        if field_key == "insurance_member_number":
            # Penalize if candidate looks like a header or all caps
            if first_candidate.isupper() and len(first_candidate) > 10:
                field_type_confidence -= 0.25  # Likely a false positive
            # Boost if it has mixed case and numbers (like "XYZ12345")
            elif any(c.isdigit() for c in first_candidate) and not first_candidate.isupper():
                field_type_confidence += 0.05
        
        # Adjust based on number of matches
        if len(regex_candidates) >= 3:
            field_type_confidence += 0.05
        elif len(regex_candidates) == 1:
            field_type_confidence -= 0.15  # Single match is risky, let LLM verify
        
        return min(field_type_confidence, 0.95)  # Cap at 95%

    def _extract_with_regex(self, text: str) -> Dict[str, List[str]]:
        """
        Extract field candidates using regex patterns with smart filtering
        
        Strategy:
        1. Extract using context-aware patterns first (labeled values)
        2. Filter out known false positives (headers, common words)
        3. Deduplicate and rank by relevance
        
        Returns: field_name -> list of candidate values (sorted by relevance)
        """
        candidates = {}

        for field_key, patterns in self.regex_patterns.items():
            field_candidates = []

            for pattern_idx, pattern in enumerate(patterns):
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    # Clean and deduplicate matches
                    cleaned_matches = []
                    for match in matches:
                        # Handle tuple results from grouped patterns (context-aware)
                        if isinstance(match, tuple):
                            cleaned = str(match[0]).strip() if match[0] else ""
                        else:
                            cleaned = str(match).strip()
                        
                        if cleaned and len(cleaned) > 1:  # Avoid single chars
                            # Apply false positive filtering
                            if not self._is_false_positive(field_key, cleaned):
                                cleaned_matches.append(cleaned)

                    # Boost priority for context-aware patterns (index 0)
                    if pattern_idx == 0 and cleaned_matches:
                        # These are labeled values - highest priority
                        field_candidates.extend([(val, 1.0) for val in cleaned_matches])
                    else:
                        # Regular patterns - normal priority
                        field_candidates.extend([(val, 0.5) for val in cleaned_matches])

            # Remove duplicates, keeping highest priority
            unique_dict = {}
            for val, priority in field_candidates:
                if val not in unique_dict or priority > unique_dict[val]:
                    unique_dict[val] = priority

            # Sort by priority (labeled first), then by length (longer = more specific)
            unique_candidates = sorted(
                unique_dict.items(),
                key=lambda x: (-x[1], -len(x[0]))
            )

            if unique_candidates:
                # Extract just the values, discard priority scores
                candidates[field_key] = [val for val, _ in unique_candidates[:5]]

        return candidates

    def _is_false_positive(self, field_key: str, value: str) -> bool:
        """
        Check if a value is a known false positive (header, section title, etc.)
        """
        value_upper = value.upper()
        
        # Check against field-specific false positives
        false_positives = self.false_positive_filters.get(field_key, [])
        
        # Exact match or word boundary match
        for fp in false_positives:
            if value_upper == fp or value_upper.startswith(fp + " ") or value_upper.endswith(" " + fp):
                return True
        
        # Generic filters for ID-like fields
        if field_key in ["insurance_member_number", "approval_number"]:
            # Avoid very short values for ID fields (likely false positives)
            if len(value) < 6:
                return True
            
            # Avoid pure letters in ID fields (unless part of pattern like "XYZ123")
            if value.isalpha():
                return True
        
        return False

    def _validate_with_llm(self, regex_candidates: Dict[str, List[str]], full_text: str, field_notes: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, str]]:
        """
        Use LLM to validate regex candidates and extract missing fields for ALL fields
        """
        validated_fields = {}

        # Create validation prompt with reviewer notes
        validation_prompt = self._create_validation_prompt(regex_candidates, full_text, field_notes)

        try:
            # Lazy import of OpenAI
            from openai import OpenAI
            if not self.client:
                self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "You are an expert at extracting insurance document information. Your task: (1) Validate and choose the best regex candidates provided, OR (2) Extract values directly from text if candidates are insufficient. IMPORTANT: Attempt to extract ALL fields comprehensively. For each field, provide your best extraction even if uncertain. Return complete JSON with all field names and confidence scores. Use null only if truly impossible to find."},
                    {"role": "user", "content": validation_prompt}
                ],
                temperature=0.1,
                max_tokens=2500
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON response
            try:
                json_start = result_text.find('{')
                json_end = result_text.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = result_text[json_start:json_end]
                    validated_data = json.loads(json_str)
                else:
                    validated_data = json.loads(result_text)

                # Process validated fields with confidence scores
                for field_key in self.regex_patterns.keys():
                    value = validated_data.get(field_key)
                    
                    # Extract confidence score from LLM
                    confidence_key = f"{field_key}_confidence"
                    llm_confidence = validated_data.get(confidence_key, 0.75)
                    
                    # Ensure confidence is valid
                    if not isinstance(llm_confidence, (int, float)):
                        llm_confidence = 0.75
                    llm_confidence = max(0.0, min(1.0, float(llm_confidence)))
                    
                    # Only add if we have a meaningful value
                    if value and str(value).strip() and str(value).lower() not in ["not found", "n/a", "none", "null", "", "unknown"]:
                        validated_fields[field_key] = {
                            'value': str(value).strip(),
                            'source': 'llm',
                            'confidence': llm_confidence,
                            'llm_confidence': llm_confidence  # Store raw LLM confidence for blending
                        }

            except json.JSONDecodeError as e:
                print(f"⚠️ LLM validation JSON parse error: {e}")
                # Fallback: use best regex candidates with default confidence
                for field_key, candidates in regex_candidates.items():
                    if candidates:
                        validated_fields[field_key] = {
                            'value': candidates[0],
                            'source': 'regex',
                            'confidence': 0.80,
                            'llm_confidence': 0.0  # No LLM extraction
                        }

        except Exception as e:
            print(f"❌ LLM validation failed: {e}")
            # Fallback to regex-only
            for field_key, candidates in regex_candidates.items():
                if candidates:
                    validated_fields[field_key] = {
                        'value': candidates[0],
                        'source': 'regex',
                        'confidence': 0.75
                    }

        return validated_fields

    def _create_validation_prompt(self, candidates: Dict[str, List[str]], full_text: str, field_notes: Optional[Dict[str, str]] = None) -> str:
        """Create prompt for LLM validation with confidence scoring and reviewer notes"""
        prompt = f"""You are an expert insurance document analyzer. Extract ALL the following fields from this insurance document text.

INSTRUCTIONS:
- For fields with candidates provided, validate and choose the best one, OR override with correct value from text
- For fields with NO candidates, actively search and extract from the text
- IMPORTANT: Do NOT return empty for any field - attempt extraction for every field
- Be thorough and look for field values anywhere in the document
- For EACH field, also provide a confidence score (0.0-1.0):
  * 0.95-1.0: Clearly labeled, exact match, very certain
  * 0.85-0.94: Found in document, reasonably certain
  * 0.75-0.84: Found but may need verification
  * 0.60-0.74: Partial match or inferred
  * Below 0.60: Not found or highly uncertain

SPECIAL FOCUS ON NAMES:
- insurance_member_name: Find in "Member Name", "Patient Name", "Subscriber Name", "Member" sections - must be a person's name
- insurance_rep_name: Find in "Authorized By", "Insurance Rep", "Case Manager", "Contact Person", "Representative" sections

Document Text:
{full_text}

EXTRACT THESE FIELDS:
"""

        # Add field-specific instructions and reviewer notes
        name_fields = ["insurance_member_name", "insurance_rep_name"]
        field_notes = field_notes or {}
        for field_key in self.regex_patterns.keys():
            field_candidates = candidates.get(field_key, [])
            prompt += f"\n{field_key}:"
            if field_candidates:
                prompt += f" [Candidates: {', '.join(field_candidates[:2])}] - Validate/correct from text"
            else:
                prompt += f" [NO candidates] - MUST extract from text"
            # Add field description
            prompt += f"\n  Description: {self.field_definitions.get(field_key, 'Unknown field')}"
            # Add reviewer note if present
            user_note = field_notes.get(field_key)
            if user_note:
                prompt += f"\n  IMPORTANT: Before extracting, please read and follow this instruction for this field:\n  {user_note}"
            # Add special guidance for name fields
            if field_key in name_fields:
                prompt += "\n  PRIORITY: Search thoroughly - this is a required name field. Look for full name (First Last)"

        prompt += """

Return a JSON object with ALL field names as keys, plus confidence scores:
{
  "insurance_member_number": "value or null",
  "insurance_member_number_confidence": 0.92,
  "insurance_member_name": "value or null", 
  "insurance_member_name_confidence": 0.88,
  ... (all other fields with confidence)
}

Use null ONLY if truly impossible to find. Confidence must be 0.0-1.0 for each field.
"""

        return prompt

    def _gap_fill_with_vlm(self, fields: Dict[str, Dict[str, str]], page_images: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Use OpenAI Vision for gap-filling on fields that LLM couldn't extract
        
        Strategy: LLM handles most fields, VLM fills remaining gaps (especially names/numbers)
        """
        filled_fields = fields.copy()

        # Diagnostic logging
        print(f"🔍 VLM Gap-fill check: page_images={type(page_images).__name__}, count={len(page_images) if page_images else 0}")
        
        if not page_images:
            print("⚠️ VLM skipped: No page images provided")
            return filled_fields

        first_page = page_images[0]
        print(f"👁️ VLM using first page: {first_page}")
        print(f"   Checking if path exists: {os.path.exists(first_page)}")
        
        if not os.path.exists(first_page):
            print(f"⚠️ VLM skipped: First page not found at {first_page}")
            return filled_fields

        try:
            print(f"👁️ VLM backend in use: {self.vlm_backend}")
            # VLM attempts for fields that LLM couldn't fill
            vlm_attempt_fields = [
                "insurance_member_name",      # Names (text-based)
                "insurance_rep_name",         # Names (text-based)
                "insurance_member_number",    # Numbers (visual confirmation)
                "insurance_company_name",     # Company name (visual)
                "approval_number",            # Numbers (visual confirmation)
                "approval_status",            # Status (visual confirmation)
                "approved_units",             # Numbers (visual layout)
                "approved_service_cpt",       # Codes (visual confirmation)
                "service_start_date",         # Dates (visual confirmation)
                "service_end_date",           # Dates (visual confirmation)
                "insurance_rep_contact",      # Contact info (visual confirmation)
                "fax_received_date",          # Date (visual confirmation)
            ]
            
            print(f"🎯 Attempting VLM gap-fill for {len(vlm_attempt_fields)} fields...")
            vlm_filled = 0
            vlm_skipped = 0
            vlm_rejected = 0
            
            for field_key in vlm_attempt_fields:
                existing = filled_fields.get(field_key, {})
                # Only gap-fill if truly empty
                if not existing.get('value', '').strip():
                    print(f"  📝 Attempting {field_key}...")
                    # Get question
                    question = self._get_vlm_question(field_key)
                    
                    if question:
                        vlm_answer = self._ask_vlm(first_page, question)
                        
                        # SAFETY: Check if VLM returned a valid answer
                        if self._is_valid_vlm_response(vlm_answer, field_key):
                            filled_fields[field_key] = {
                                'value': vlm_answer,
                                'source': 'vlm',
                                'confidence': 0.72
                            }
                            print(f"  ✅ VLM filled {field_key}: {vlm_answer}")
                            vlm_filled += 1
                        else:
                            print(f"  ❌ VLM rejected {field_key} (invalid response)")
                            vlm_rejected += 1
                    else:
                        print(f"  ⏭️ No question for {field_key}")
                        vlm_skipped += 1
                else:
                    # Already has a value, skip
                    pass
            
            print(f"✅ VLM gap-fill complete: {vlm_filled} filled, {vlm_rejected} rejected, {vlm_skipped} skipped")

        except Exception as e:
            print(f"❌ VLM gap-filling failed: {e}")

        return filled_fields

    def _is_valid_vlm_response(self, response: str, field_key: str) -> bool:
        """
        Validate VLM response - reject refusals and privacy rejections, accept valid data
        
        Returns: True if response is valid data, False if it's an error/refusal
        """
        if not response or not response.strip():
            return False
        
        response_lower = response.lower().strip()
        
        # List of common VLM refusal patterns - STRICT LIST only
        refusal_patterns = [
            "i'm sorry",
            "i apologize",
            "i cannot",
            "i can't",
            "cannot provide",
            "can't provide",
            "cannot determine",
            "can't determine",
            "cannot reveal",
            "can't reveal",
            "don't know",
            "i don't know",
            "cannot find",
            "can't find",
            "not visible",
            "cannot see",
            "can't see",
            "privacy",
            "confidential",
            "identify individuals",
            "personal information",
        ]
        
        # Check if response contains any refusal pattern
        for pattern in refusal_patterns:
            if pattern in response_lower:
                return False
        
        # Reject if it looks like a repeated question (too many words from the prompt)
        if "?" in response and len(response.split()) < 3:
            return False
        
        # Field-specific validations (be lenient but sensible)
        if field_key in ["insurance_member_number", "approval_number"]:
            # These should have alphanumeric content
            alphanumeric_count = sum(1 for c in response if c.isalnum())
            # Require at least 40% alphanumeric (relaxed from 50%)
            if alphanumeric_count < len(response) * 0.4:
                return False
            # Should be relatively short (IDs don't contain essays)
            if len(response) > 50:
                return False
        
        if field_key in ["approved_units"]:
            # Should contain at least one digit
            digit_count = sum(1 for c in response if c.isdigit())
            if digit_count == 0:
                return False
            # Should be relatively short
            if len(response) > 20:
                return False
        
        if field_key in ["service_start_date", "service_end_date", "fax_received_date"]:
            # Date fields should be short and contain digits
            if len(response) > 50:
                return False
            digit_count = sum(1 for c in response if c.isdigit())
            if digit_count < 2:  # At least 2 digits for dates
                return False
        
        if field_key in ["insurance_rep_contact"]:
            # Phone numbers should contain digits
            digit_count = sum(1 for c in response if c.isdigit())
            if digit_count < 3:  # At least 3 digits for phone
                return False
        
        # Accept names, company names, and status fields if they passed refusal check
        # They are text-based and valid if they don't contain refusals
        if field_key in ["insurance_member_name", "insurance_rep_name", 
                         "insurance_company_name", "approval_status",
                         "approved_service_cpt"]:
            # Should be relatively short (reasonable field values)
            if len(response) > 100:
                return False
            # Should not be mostly special characters
            letter_count = sum(1 for c in response if c.isalpha() or c.isdigit())
            if letter_count < len(response) * 0.3:
                return False
        
        return True

    def _ask_vlm(self, image_path: str, question: str) -> str:
        """Dispatch to the configured VLM backend"""
        if self.vlm_backend == "donut":
            print("👁️ Routing VLM question to Donut backend")
            return self._ask_donut_vlm(image_path, question)
        print("👁️ Routing VLM question to OpenAI Vision backend")
        return self._ask_openai_vision(image_path, question)

    def _ask_openai_vision(self, image_path: str, question: str) -> str:
        """Ask OpenAI Vision a question about an image"""
        try:
            # Lazy import of OpenAI
            from openai import OpenAI
            if not self.client:
                self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=100
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"OpenAI Vision error: {e}")
            return ""

    def _ask_donut_vlm(self, image_path: str, question: str) -> str:
        """Run Donut VLM (VisionEncoderDecoder) for gap-filling."""
        try:
            from transformers import DonutProcessor, VisionEncoderDecoderModel
            import torch
        except Exception as exc:  # pragma: no cover - dependency guard
            print(f"Donut VLM unavailable: {exc}")
            return ""

        try:
            if not hasattr(self, "donut_processor") or not hasattr(self, "donut_model"):
                model_path = self.vlm_model_path
                self.donut_processor = DonutProcessor.from_pretrained(model_path)
                self.donut_model = VisionEncoderDecoderModel.from_pretrained(model_path)
                self.donut_device = "cuda" if torch.cuda.is_available() else "cpu"
                self.donut_model.to(self.donut_device)

            processor = self.donut_processor
            model = self.donut_model
            device = self.donut_device

            from PIL import Image
            image = Image.open(image_path).convert("RGB")
            pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)

            prompt = f"<s_question>{question}</s_question><s_answer>"
            decoder_input_ids = processor.tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids.to(device)

            outputs = model.generate(
                pixel_values=pixel_values,
                decoder_input_ids=decoder_input_ids,
                max_length=processor.tokenizer.model_max_length,
                num_beams=1,
                early_stopping=True,
            )

            decoded = processor.batch_decode(outputs, skip_special_tokens=True)[0]
            answer = decoded.replace(prompt, "").strip()

            # Keep the last non-empty line to avoid prompt echoes
            answer_lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
            if answer_lines:
                answer = answer_lines[-1]

            # Reject if the answer still looks like the prompt
            lower_answer = answer.lower()
            if any(
                lower_answer.startswith(prefix)
                for prefix in [
                    "what name appears",
                    "find and read",
                    "what is the",
                    "reply with",
                    "look for",
                    "insurance representative",
                ]
            ):
                return ""

            return answer

        except Exception as e:
            print(f"Donut VLM error: {e}")
            return ""

    def _get_vlm_question(self, field_key: str) -> str:
        """Get the appropriate question for VLM based on field type - optimized to avoid privacy triggers"""
        questions = {
            # Names - use indirect approach to avoid privacy filter
            "insurance_member_name": "What name appears in the member name or patient name field on this document? Read the text exactly as shown.",
            
            "approval_status": "What is the APPROVAL STATUS? Look for: Approved, Denied, Pending, Partially Approved, or any similar status text. Reply with the exact status only.",
            
            "insurance_member_number": "Find and read the ID number on this document. Look for: Member ID, Subscriber ID, Policy Number, or ID Number. Reply with only the ID number, nothing else.",
            
            "approval_number": "Find and read the authorization or approval number on this document. Look for: Authorization Number, Approval Number, Auth #, Reference #. Reply with only the number, nothing else.",
            
            "insurance_company_name": "What insurance company is this document from? Reply with only the company name, nothing else.",
            
            "approved_service_cpt": "Find the CPT code or service code that is approved or authorized. Reply with only the code, nothing else.",
            
            "approved_units": "How many units, visits, or sessions are approved? Look for a number. Reply with only the number, nothing else.",
            
            "service_start_date": "Find the start date of service, coverage start date, or begin date. Reply with only the date in MM/DD/YYYY format, nothing else.",
            
            "service_end_date": "Find the end date of service, coverage end date, or through date. Reply with only the date in MM/DD/YYYY format, nothing else.",
            
            # Rep name - use indirect approach
            "insurance_rep_name": "What name appears as the insurance representative or case manager on this document? Read the text exactly as shown.",
            
            "insurance_rep_contact": "Find the phone number for the insurance representative or contact person. Reply with only the phone number, nothing else.",
            
            "fax_received_date": "What is the date this fax was received or the document date? Reply with only the date in MM/DD/YYYY format, nothing else."
        }
        return questions.get(field_key, None)

    def _apply_validation_engine(self, fields: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """Apply validation and canonicalization engine"""
        # Get payer name for context
        payer_name = None
        for field_key, field_data in fields.items():
            if field_key == 'insurance_company_name':
                payer_name = field_data.get('value', '')
                break

        # Validate and canonicalize
        validation_results = validation_engine.validate_and_canonicalize(fields, payer_name)

        # Apply agree-to-finalize mode
        can_finalize, review_reasons = validation_engine.get_agree_to_finalize_decision(validation_results)

        if not can_finalize:
            print(f"⚠️ Agree-to-finalize mode: Review required for {len(review_reasons)} fields")
        else:
            print("✅ All fields passed validation - auto-finalizing")

        # Return validated fields with canonical values
        validated_fields = {}
        for field_key, field_data in fields.items():
            if field_key in validation_results:
                result = validation_results[field_key]
                validated_fields[field_key] = {
                    'value': result.canonical_value,
                    'source': field_data.get('source', 'unknown'),
                    'confidence': field_data.get('confidence', 0.5),
                    'validation_passed': not result.requires_review  # Fixed: was result.is_valid
                }

        return validated_fields

    def _calculate_confidence(self, field_key: str, value: str, source: str) -> float:
        """Calculate confidence score for extracted field"""
        if not value or not value.strip():
            return 0.0

        # Base confidence by source
        base_confidence = {
            'regex': 0.90,  # High confidence for regex matches
            'llm': 0.85,    # Good confidence for LLM
            'vlm': 0.75     # Lower for vision (can be noisy)
        }.get(source, 0.5)

        # Adjust based on field type and value characteristics
        if field_key in ['insurance_company_name', 'insurance_member_name']:
            # Name fields - check for reasonable length and format
            if len(value.strip()) < 3:
                base_confidence *= 0.7
            elif len(value.strip()) > 50:
                base_confidence *= 0.8
        elif field_key in ['insurance_member_number', 'approval_number']:
            # ID fields - check for alphanumeric content
            if not any(c.isalnum() for c in value):
                base_confidence *= 0.5
        elif 'date' in field_key:
            # Date fields - check for date-like patterns
            if not any(pattern in value for pattern in ['/', '-', '.']):
                base_confidence *= 0.6
        elif 'phone' in field_key.lower():
            # Phone fields - check for digits
            digits = ''.join(c for c in value if c.isdigit())
            if len(digits) < 7:
                base_confidence *= 0.7

        return min(base_confidence, 0.95)  # Cap at 95%

    # Field definitions for the system
    field_definitions = {
        "insurance_company_name": "Name of the insurance company (e.g., Blue Cross, Aetna, United Healthcare)",
        "insurance_member_number": "Member ID, Subscriber ID, or Policy Number",
        "insurance_member_name": "Name of the insured member or patient",
        "approval_status": "Whether the request was Approved, Denied, or other status",
        "approval_number": "Authorization or approval reference number",
        "approved_service_cpt": "Approved service codes, CPT codes, or procedure codes",
        "approved_units": "Number of approved units, visits, or sessions",
        "service_start_date": "Start date of service coverage (MM/DD/YYYY)",
        "service_end_date": "End date of service coverage (MM/DD/YYYY)",
        "insurance_rep_name": "Name of the insurance representative or case manager",
        "insurance_rep_contact": "Phone number of the insurance representative",
        "fax_received_date": "Date the fax was received (MM/DD/YYYY)"
    }