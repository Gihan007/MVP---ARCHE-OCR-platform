"""
Confidence & Validation Engine for OCR-ArcheAI
Provides canonicalization, payer-aware validation, and gating rules for extracted fields
"""
import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """Result of field validation"""
    field_key: str
    original_value: str
    canonical_value: str
    confidence_score: float
    validation_errors: List[str]
    requires_review: bool
    payer_specific_rules: List[str]

class ValidationEngine:
    """Engine for validating and canonicalizing extracted insurance fields"""

    def __init__(self):
        # Payer-specific validation rules
        self.payer_rules = {
            "aetna": {
                "member_id_pattern": r"^[A-Z]{2}\d{8,10}$",  # e.g., AB12345678
                "phone_format": r"^\d{3}-\d{3}-\d{4}$",
                "member_name_required": True
            },
            "blue_cross": {
                "member_id_pattern": r"^[A-Z]{1,2}\d{7,12}$",
                "phone_format": r"^\(\d{3}\)\s?\d{3}-\d{4}$",
                "group_number_required": True
            },
            "united_healthcare": {
                "member_id_pattern": r"^\d{9,12}$",
                "phone_format": r"^\d{3}-\d{3}-\d{4}$",
                "effective_date_required": True
            },
            "cigna": {
                "member_id_pattern": r"^[A-Z]\d{8,10}$",
                "phone_format": r"^\d{10}$",
                "subscriber_id_required": True
            }
        }

        # Field-specific canonicalization patterns
        self.canonicalizers = {
            "phone": self._canonicalize_phone,
            "date": self._canonicalize_date,
            "name": self._canonicalize_name,
            "member_number": self._canonicalize_member_number,
            "currency": self._canonicalize_currency
        }

    def validate_and_canonicalize(self, fields: Dict[str, Any], payer_name: str = None) -> Dict[str, ValidationResult]:
        """
        Validate and canonicalize all extracted fields

        Args:
            fields: Dict of field_key -> extracted_value (can be string or dict with 'value' and 'confidence')
            payer_name: Name of insurance payer for payer-specific validation

        Returns:
            Dict of field_key -> ValidationResult
        """
        results = {}

        for field_key, field_data in fields.items():
            # Handle both string values and dict values with confidence
            if isinstance(field_data, dict):
                value = field_data.get('value', '')
                initial_confidence = field_data.get('confidence', 0.5)
            else:
                value = field_data
                initial_confidence = 0.5  # Default confidence for legacy string inputs
            
            if not value or value.strip() == "":
                continue

            # Canonicalize the value
            canonical_value = self._canonicalize_field(field_key, value)

            # Validate the field
            validation_errors = []
            confidence_score = initial_confidence  # Start with confidence from extraction
            requires_review = False
            payer_rules_applied = []

            # Apply general validation rules
            validation_errors.extend(self._validate_field_general(field_key, canonical_value))
            confidence_score *= self._calculate_general_confidence(field_key, canonical_value, validation_errors)

            # Apply payer-specific validation if payer is known
            if payer_name:
                payer_key = self._normalize_payer_name(payer_name)
                if payer_key in self.payer_rules:
                    payer_errors, payer_confidence, payer_rules = self._validate_field_payer_specific(
                        field_key, canonical_value, payer_key
                    )
                    validation_errors.extend(payer_errors)
                    confidence_score *= payer_confidence
                    payer_rules_applied.extend(payer_rules)

            # Apply gating rules to determine if review is needed
            requires_review = self._apply_gating_rules(field_key, confidence_score, validation_errors)

            results[field_key] = ValidationResult(
                field_key=field_key,
                original_value=value,
                canonical_value=canonical_value,
                confidence_score=round(confidence_score, 2),
                validation_errors=validation_errors,
                requires_review=requires_review,
                payer_specific_rules=payer_rules_applied
            )

        return results

    def _canonicalize_field(self, field_key: str, value: str) -> str:
        """Canonicalize a field value based on its type"""
        value = value.strip()

        # Determine field type and apply appropriate canonicalizer
        if "phone" in field_key.lower() or "contact" in field_key.lower():
            return self.canonicalizers["phone"](value)
        elif "date" in field_key.lower():
            return self.canonicalizers["date"](value)
        elif "name" in field_key.lower():
            return self.canonicalizers["name"](value)
        elif "member" in field_key.lower() and ("number" in field_key.lower() or "id" in field_key.lower()):
            return self.canonicalizers["member_number"](value)
        elif any(term in value.lower() for term in ["$", "usd", "dollars"]):
            return self.canonicalizers["currency"](value)
        else:
            # No specific canonicalization needed
            return value

    def _canonicalize_phone(self, value: str) -> str:
        """Canonicalize phone numbers to standard format"""
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', value)

        if len(digits) == 10:
            # US phone number
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits.startswith('1'):
            # US phone number with country code
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            # Return as-is if not standard format
            return value

    def _canonicalize_date(self, value: str) -> str:
        """Canonicalize dates to MM/DD/YYYY format"""
        # Common date patterns
        patterns = [
            (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda m: f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"),  # MM/DD/YYYY
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda m: f"{int(m.group(2)):02d}/{int(m.group(3)):02d}/{m.group(1)}"),  # YYYY-MM-DD
            (r'(\d{1,2})-(\d{1,2})-(\d{4})', lambda m: f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"),  # MM-DD-YYYY
            (r'(\d{1,2})\s+(\w{3})\s+(\d{4})', self._month_name_to_date),  # DD Mon YYYY
        ]

        for pattern, formatter in patterns:
            match = re.search(pattern, value, re.IGNORECASE)
            if match:
                try:
                    return formatter(match)
                except:
                    continue

        return value  # Return original if no pattern matches

    def _month_name_to_date(self, match) -> str:
        """Convert month name to date"""
        day, month_name, year = match.groups()
        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        month = month_map.get(month_name.lower()[:3])
        if month:
            return f"{int(day):02d}/{month:02d}/{year}"
        return f"{day} {month_name} {year}"

    def _canonicalize_name(self, value: str) -> str:
        """Canonicalize names to Title Case"""
        # Split by common separators and capitalize each part
        parts = re.split(r'[,\s]+', value.strip())
        capitalized_parts = []

        for part in parts:
            if part:
                # Capitalize first letter, lowercase rest
                capitalized_parts.append(part[0].upper() + part[1:].lower())

        return ' '.join(capitalized_parts)

    def _canonicalize_member_number(self, value: str) -> str:
        """Canonicalize member numbers by removing extra spaces/hyphens"""
        # Remove spaces, hyphens, and other non-alphanumeric except letters and numbers
        cleaned = re.sub(r'[^\w]', '', value.upper())
        return cleaned

    def _canonicalize_currency(self, value: str) -> str:
        """Canonicalize currency amounts"""
        # Extract numeric value
        match = re.search(r'[\d,]+\.?\d*', value)
        if match:
            amount = match.group().replace(',', '')
            try:
                # Format as currency
                return f"${float(amount):,.2f}"
            except ValueError:
                pass
        return value

    def _validate_field_general(self, field_key: str, value: str) -> List[str]:
        """Apply general validation rules"""
        errors = []

        # Required field checks
        if field_key in ["insurance_member_name", "insurance_company_name"] and len(value) < 2:
            errors.append("Value too short for name field")

        # Format validation
        if "phone" in field_key.lower():
            if not re.search(r'\(\d{3}\)\s?\d{3}-\d{4}', value):
                errors.append("Phone number not in standard format")

        if "date" in field_key.lower():
            if not re.search(r'\d{1,2}/\d{1,2}/\d{4}', value):
                errors.append("Date not in MM/DD/YYYY format")

        # Length validation
        if len(value) > 100:
            errors.append("Value suspiciously long")

        return errors

    def _validate_field_payer_specific(self, field_key: str, value: str, payer_key: str) -> Tuple[List[str], float, List[str]]:
        """Apply payer-specific validation rules"""
        errors = []
        confidence = 1.0
        rules_applied = []

        rules = self.payer_rules.get(payer_key, {})

        # Member ID validation
        if "member" in field_key.lower() and ("number" in field_key.lower() or "id" in field_key.lower()):
            pattern = rules.get("member_id_pattern")
            if pattern:
                if not re.match(pattern, value):
                    errors.append(f"Member ID doesn't match {payer_key.upper()} format")
                    confidence *= 0.5
                else:
                    rules_applied.append(f"Validated against {payer_key.upper()} member ID pattern")

        # Phone format validation
        if "phone" in field_key.lower() or "contact" in field_key.lower():
            phone_pattern = rules.get("phone_format")
            if phone_pattern:
                if not re.search(phone_pattern, value):
                    errors.append(f"Phone format doesn't match {payer_key.upper()} requirements")
                    confidence *= 0.7
                else:
                    rules_applied.append(f"Validated phone format for {payer_key.upper()}")

        # Required field checks
        if rules.get("member_name_required") and field_key == "insurance_member_name" and not value:
            errors.append(f"Member name required for {payer_key.upper()}")
            confidence *= 0.8

        if rules.get("group_number_required") and "group" in field_key.lower() and not value:
            errors.append(f"Group number required for {payer_key.upper()}")
            confidence *= 0.8

        return errors, confidence, rules_applied

    def _calculate_general_confidence(self, field_key: str, value: str, errors: List[str]) -> float:
        """Calculate confidence score based on general validation"""
        confidence = 1.0

        # Reduce confidence for each error
        confidence *= (0.9 ** len(errors))

        # Length-based confidence
        if len(value) < 3:
            confidence *= 0.7
        elif len(value) > 50:
            confidence *= 0.8

        # Pattern-based confidence
        if re.search(r'\b(not|none|n/a|unknown)\b', value, re.IGNORECASE):
            confidence *= 0.3

        return confidence

    def _apply_gating_rules(self, field_key: str, confidence_score: float, errors: List[str]) -> bool:
        """Apply gating rules to determine if human review is required"""
        # Critical fields always need higher confidence
        critical_fields = [
            "insurance_member_name",
            "approval_status",
            "insurance_member_number",
            "approval_number"
        ]

        if field_key in critical_fields:
            # Critical fields need 90%+ confidence and no errors
            return confidence_score < 0.9 or len(errors) > 0
        else:
            # Non-critical fields need 70%+ confidence
            return confidence_score < 0.7

    def _normalize_payer_name(self, payer_name: str) -> str:
        """Normalize payer name to match rule keys"""
        name = payer_name.lower().replace(' ', '').replace('-', '')

        # Common mappings
        mappings = {
            "aetna": "aetna",
            "bluecross": "blue_cross",
            "bluecrossblueshield": "blue_cross",
            "unitedhealthcare": "united_healthcare",
            "united": "united_healthcare",
            "cigna": "cigna"
        }

        return mappings.get(name, name)

    def get_agree_to_finalize_decision(self, validation_results: Dict[str, ValidationResult]) -> Tuple[bool, List[str]]:
        """
        Apply agree-to-finalize mode: only finalize if multiple validation checks agree

        Returns:
            (can_finalize, reasons_for_review)
        """
        reasons = []
        can_finalize = True

        for field_key, result in validation_results.items():
            if result.requires_review:
                reasons.append(f"{field_key}: {', '.join(result.validation_errors)}")
                can_finalize = False

        return can_finalize, reasons


# Singleton instance
validation_engine = ValidationEngine()