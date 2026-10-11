import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import relationship
from app.db.session import Base

def generate_file_id() -> str:
    return uuid.uuid4().hex[:12]

class FileRecord(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=generate_file_id)
    filename = Column(String(255), nullable=False)
    file_format = Column(String(50), nullable=False)  # "shapefile" or "kml"
    file_size_bytes = Column(Integer, default=0)
    crs = Column(String(100), default="EPSG:4326")
    feature_count = Column(Integer, default=0)
    status = Column(String(50), default="PROCESSING")  # PROCESSING, COMPLETED, FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    features = relationship("FeatureRecord", back_populates="file", cascade="all, delete-orphan", order_by="FeatureRecord.feature_index")

class FeatureRecord(Base):
    __tablename__ = "features"
    __table_args__ = (
        Index("ix_features_file_id_idx", "file_id", "feature_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), index=True, nullable=False)
    feature_index = Column(Integer, nullable=False)
    feature_identifier = Column(String(255), nullable=True)
    geometry_type = Column(String(100), nullable=False)
    geometry = Column(JSON, nullable=False)  # GeoJSON dict
    properties = Column(JSON, default=dict)
    original_crs = Column(String(100), nullable=False)
    projected_crs = Column(String(100), nullable=True)
    measurements = Column(JSON, nullable=True)  # {'area_sq_m': ..., 'length_m': ...}
    notes = Column(Text, nullable=True)

    file = relationship("FileRecord", back_populates="features")
