# 8 Authorization Templates Configuration for Healthcare Payers

AUTHORIZATION_TEMPLATES = {
    "anthem": {
        "company_names": ["Anthem", "Anthem Blue Cross", "Anthem Insurance", "BCBS", "Anthem BCBS", "Anthem Health"],
        "keywords": ["authorization", "approval", "authorization number", "approved", "prior authorization"],
        "approval_status_keywords": ["approved", "denied", "pending", "conditional"],
        "required_fields": ["authorization_number", "approval_status", "member_id"],
    },
    "caresource": {
        "company_names": ["CareCourse", "CareSource", "Care Source", "Caresource Health"],
        "keywords": ["authorization", "approval request", "certification", "auth"],
        "approval_status_keywords": ["approved", "denied", "pending"],
        "required_fields": ["authorization_number", "approval_status"],
    },
    "molina": {
        "company_names": ["Molina", "Molina Healthcare", "Molina Health"],
        "keywords": ["prior authorization", "auth request", "approval", "certification"],
        "approval_status_keywords": ["approved", "denied", "pending"],
        "required_fields": ["auth_number", "status"],
    },
    "buckeye": {
        "company_names": ["Buckeye", "Buckeye Health Plan", "Buckeye Community"],
        "keywords": ["authorization", "prior authorization", "approval"],
        "approval_status_keywords": ["approved", "not approved", "pending"],
        "required_fields": ["authorization_number"],
    },
    "humana": {
        "company_names": ["Humana", "Humana Insurance", "Humana Health"],
        "keywords": ["authorization", "approval", "certification"],
        "approval_status_keywords": ["approved", "denied", "conditional"],
        "required_fields": ["auth_number", "member_id"],
    },
    "united": {
        "company_names": ["United Healthcare", "UnitedHealth", "UHONE", "UHC", "United Health"],
        "keywords": ["authorization", "approval", "certified"],
        "approval_status_keywords": ["approved", "denied", "modified"],
        "required_fields": ["authorization_number"],
    },
    "amerihealth": {
        "company_names": ["AmeriHealth", "Amerihealth Caritas", "Amerihealth PA"],
        "keywords": ["authorization", "approval", "prior auth"],
        "approval_status_keywords": ["approved", "denied"],
        "required_fields": ["auth_number", "member_id"],
    },
    "aetna": {
        "company_names": ["Aetna", "Aetna Insurance", "Aetna Health"],
        "keywords": ["authorization", "approval", "certification"],
        "approval_status_keywords": ["approved", "denied"],
        "required_fields": ["authorization_number", "member_id"],
    },
}

COMMON_PA_KEYWORDS = [
    "prior authorization",
    "pre-authorization",
    "precertification",
    "approval request",
    "certification request",
    "authorization number",
    "approval status",
    "authorization",
    "approval",
    "certified",
    "certification",
    "cpt code",
    "service date",
    "member id",
    "member number",
    "patient name",
    "procedure",
    "diagnosi",
    "medical necessity",
    "requested",
]

NON_PA_KEYWORDS = [
    "explanation of benefits",
    "eob",
    "claims summary",
    "payment summary",
    "visit summary",
    "receipt",
    "invoice",
    "explanation of benefit",
]
