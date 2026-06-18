"""
Initialize the PostgreSQL database for production
"""
from shared.database import engine, Base
from shared.models.fax_job import FaxJob
from shared.models.fax_extracted_field import FaxExtractedField
from shared.models.human_label import HumanLabel

def init_database():
    """Create all database tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully!")
    print("Database: PostgreSQL (fax_db)")

if __name__ == "__main__":
    init_database()
