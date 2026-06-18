from sqlalchemy import Column, Integer, String, Float, Text, JSON, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from shared.database import Base


class FaxExtractedField(Base):
    __tablename__ = "fax_extracted_fields"

    id = Column(Integer, primary_key=True, index=True)
    fax_job_id = Column(Integer, ForeignKey("fax_jobs.id"), nullable=False)
    field_key = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    method = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    evidence_bbox = Column(JSON, nullable=True)
    evidence_text = Column(Text, nullable=True)
    candidates = Column(JSON, nullable=True)
    validated = Column(Boolean, nullable=True)
    human_modified = Column(Boolean, nullable=True)
    human_modified_at = Column(DateTime, nullable=True)
    human_modified_by = Column(String, nullable=True)
    original_ai_value = Column(Text, nullable=True)

    # Relationships
    fax_job = relationship("FaxJob", back_populates="extracted_fields")