from typing import Any, Optional, Dict, List
from pydantic import BaseModel, Field
from datetime import datetime

class FileBaseResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str
    status: str

    model_config = {"from_attributes": True}

class FileDetailResponse(FileBaseResponse):
    file_format: str
    file_size_bytes: int
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class FeatureMeasurementDetail(BaseModel):
    area_sq_m: Optional[float] = Field(None, description="Area in square meters")
    area_hectares: Optional[float] = Field(None, description="Area in hectares")
    area_sq_km: Optional[float] = Field(None, description="Area in square kilometers")
    length_m: Optional[float] = Field(None, description="Length in meters")
    length_km: Optional[float] = Field(None, description="Length in kilometers")

class FeatureResponse(BaseModel):
    feature_id: str = Field(..., description="Feature ID or index")
    geometry_type: str
    geometry: Dict[str, Any]
    crs: str = Field(..., description="Original coordinate reference system")
    projected_crs: Optional[str] = Field(None, description="Projected CRS used for measurement calculations")
    properties: Dict[str, Any] = Field(default_factory=dict)
    measurements: Optional[FeatureMeasurementDetail] = None
    notes: Optional[str] = None

    model_config = {"from_attributes": True}

class MeasurementSummary(BaseModel):
    geometry_type_breakdown: Dict[str, int]
    total_area_sq_m: float = 0.0
    total_area_hectares: float = 0.0
    total_area_sq_km: float = 0.0
    total_length_m: float = 0.0
    total_length_km: float = 0.0

class FileMeasurementsResponse(BaseModel):
    id: str
    filename: str
    crs: str
    status: str
    feature_count: int
    summary: MeasurementSummary
    features: List[FeatureResponse]

    model_config = {"from_attributes": True}
