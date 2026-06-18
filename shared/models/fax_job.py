from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from shared.database import Base


class FaxJob(Base):
    __tablename__ = "fax_jobs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    status = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True)
    finalized_at = Column(DateTime, nullable=True)
    total_pages = Column(Integer, nullable=True)
    review_needed = Column(Boolean, nullable=True)
    has_human_modifications = Column(Boolean, nullable=True)
    modified_fields = Column(Text, nullable=True)

    # Relationships
    extracted_fields = relationship("FaxExtractedField", back_populates="fax_job")
    human_labels = relationship("HumanLabel", back_populates="fax_job")