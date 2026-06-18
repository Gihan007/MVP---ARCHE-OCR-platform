from sqlalchemy import Column, Integer, String, Float, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from shared.database import Base


class HumanLabel(Base):
    __tablename__ = "human_labels"

    id = Column(Integer, primary_key=True, index=True)
    fax_job_id = Column(Integer, ForeignKey("fax_jobs.id"), nullable=False)
    field_key = Column(String, nullable=False)
    ai_value = Column(Text, nullable=True)
    ai_confidence = Column(Float, nullable=True)
    human_value = Column(Text, nullable=True)
    human_action = Column(String, nullable=True)
    review_time_seconds = Column(Float, nullable=True)
    reviewer_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True)
    page_number = Column(Integer, nullable=True)
    bbox = Column(JSON, nullable=True)

    # Relationships
    fax_job = relationship("FaxJob", back_populates="human_labels")