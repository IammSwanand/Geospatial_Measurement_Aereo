from pathlib import Path
from typing import List, Optional
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.db.models import FileRecord, FeatureRecord, generate_file_id
from app.schemas.file import (
    FileBaseResponse,
    FileDetailResponse,
    FileMeasurementsResponse,
    FeatureResponse,
    MeasurementSummary,
    FeatureMeasurementDetail,
)
from app.core.exceptions import InvalidGeospatialFileError
from app.core.security import validate_magic_bytes, validate_zip_security, validate_kml_security
from app.core.rate_limiter import rate_limit
from app.services.file_processor import process_geospatial_file

router = APIRouter(prefix="/files", tags=["Files"])

@router.post(
    "/",
    response_model=FileBaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_UPLOADS_PER_MINUTE, 60, bucket="uploads"))],
)
@router.post(
    "",
    response_model=FileBaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_UPLOADS_PER_MINUTE, 60, bucket="uploads"))],
    include_in_schema=False,
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Geospatial file (.zip containing Shapefile or .kml)"),
    sync: bool = Query(False, description="Process synchronously instead of in background"),
    db: Session = Depends(get_db),
):
    """
    Upload and process a geospatial file (.zip containing Shapefile, or .kml).
    Asynchronous by default for extreme scalability with large files.
    Secured against content spoofing, zip-bombs, zip-slip, malicious extensions, and XXE attacks.
    """
    filename = Path(file.filename or "unknown").name
    suffix = Path(filename).suffix.lower()

    if suffix not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{suffix}'. Supported formats are: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # 1. Content Spoofing Check (Magic Bytes Verification)
    try:
        header = await file.read(512)
        await file.seek(0)
        validate_magic_bytes(header, suffix)
    except InvalidGeospatialFileError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    file_id = generate_file_id()
    file_format = "shapefile" if suffix == ".zip" else "kml"
    saved_filename = f"{file_id}_{filename}"
    saved_path = settings.UPLOAD_DIR / saved_filename

    # Save uploaded file safely
    try:
        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded file: {str(e)}"
        )

    # 2. File Size Enforcement
    file_size = saved_path.stat().st_size
    if file_size > settings.MAX_UPLOAD_SIZE_BYTES:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed upload size of {int(settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024))}MB."
        )

    # 3. Deep Payload Security Inspection (Zip-Bomb, Zip-Slip, XXE, Malicious Files)
    try:
        if suffix == ".zip":
            validate_zip_security(saved_path)
        elif suffix == ".kml":
            validate_kml_security(saved_path)
    except InvalidGeospatialFileError as e:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    file_record = FileRecord(
        id=file_id,
        filename=filename,
        file_format=file_format,
        file_size_bytes=file_size,
        crs="PENDING",
        feature_count=0,
        status="PROCESSING",
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    if sync:
        process_geospatial_file(file_id, str(saved_path), db=db)
        db.refresh(file_record)
        return file_record
    else:
        background_tasks.add_task(process_geospatial_file, file_id, str(saved_path))
        return file_record

@router.get(
    "/{file_id}/",
    response_model=FileBaseResponse,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
)
@router.get(
    "/{file_id}",
    response_model=FileBaseResponse,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
    include_in_schema=False,
)
def get_file_info(file_id: str, db: Session = Depends(get_db)):
    """
    Returns information about the uploaded file.
    Example:
    {
      "id": "abc123",
      "filename": "survey.kml",
      "feature_count": 120,
      "crs": "EPSG:4326",
      "status": "COMPLETED"
    }
    """
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found."
        )
    return file_record

@router.get(
    "/{file_id}/measurements/",
    response_model=FileMeasurementsResponse,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
)
@router.get(
    "/{file_id}/measurements",
    response_model=FileMeasurementsResponse,
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
    include_in_schema=False,
)
def get_file_measurements(file_id: str, db: Session = Depends(get_db)):
    """
    Returns measurements for the features in the file.
    Includes geometry type, original and projected CRS, properties, and area/length metrics.
    """
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found."
        )

    if file_record.status == "PROCESSING":
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="File is currently being processed. Please retry shortly."
        )

    if file_record.status == "FAILED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File processing failed: {file_record.error_message}"
        )

    features = (
        db.query(FeatureRecord)
        .filter(FeatureRecord.file_id == file_id)
        .order_by(FeatureRecord.feature_index)
        .all()
    )

    feature_responses = []
    geom_breakdown: dict[str, int] = {}
    total_area_sq_m = 0.0
    total_length_m = 0.0

    for f in features:
        geom_type = f.geometry_type
        geom_breakdown[geom_type] = geom_breakdown.get(geom_type, 0) + 1

        measurements_detail = None
        if f.measurements:
            measurements_detail = FeatureMeasurementDetail(**f.measurements)
            if "area_sq_m" in f.measurements and f.measurements["area_sq_m"]:
                total_area_sq_m += f.measurements["area_sq_m"]
            if "length_m" in f.measurements and f.measurements["length_m"]:
                total_length_m += f.measurements["length_m"]

        feature_responses.append(
            FeatureResponse(
                feature_id=f.feature_identifier or str(f.feature_index),
                geometry_type=f.geometry_type,
                geometry=f.geometry,
                crs=f.original_crs,
                projected_crs=f.projected_crs,
                properties=f.properties or {},
                measurements=measurements_detail,
                notes=f.notes,
            )
        )

    summary = MeasurementSummary(
        geometry_type_breakdown=geom_breakdown,
        total_area_sq_m=round(total_area_sq_m, 2),
        total_area_hectares=round(total_area_sq_m / 10_000.0, 4),
        total_area_sq_km=round(total_area_sq_m / 1_000_000.0, 6),
        total_length_m=round(total_length_m, 2),
        total_length_km=round(total_length_m / 1_000.0, 4),
    )

    return FileMeasurementsResponse(
        id=file_record.id,
        filename=file_record.filename,
        crs=file_record.crs,
        status=file_record.status,
        feature_count=file_record.feature_count,
        summary=summary,
        features=feature_responses,
    )

@router.get(
    "/",
    response_model=List[FileDetailResponse],
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
)
@router.get(
    "",
    response_model=List[FileDetailResponse],
    dependencies=[Depends(rate_limit(settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60, bucket="api"))],
    include_in_schema=False,
)
def list_files(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    """List all uploaded geospatial files with pagination and filtering."""
    query = db.query(FileRecord)
    if status_filter:
        query = query.filter(FileRecord.status == status_filter.upper())
    return query.order_by(FileRecord.created_at.desc()).offset(skip).limit(limit).all()

@router.delete("/{file_id}/", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    """Deletes an uploaded file record and its extracted features."""
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found."
        )

    # Delete physical file from storage if present
    saved_filename = f"{file_id}_{file_record.filename}"
    saved_path = settings.UPLOAD_DIR / saved_filename
    if saved_path.exists():
        try:
            saved_path.unlink()
        except Exception:
            pass

    db.delete(file_record)
    db.commit()
    return None
