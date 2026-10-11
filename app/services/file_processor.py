import time
import logging
from typing import Optional
from pathlib import Path
from shapely.geometry import mapping
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import FileRecord, FeatureRecord
from app.services.parsers import get_parser
from app.services.measurement_service import MeasurementService

logger = logging.getLogger(__name__)

def process_geospatial_file(file_id: str, file_path_str: str, db: Optional[Session] = None) -> None:
    """
    Worker task to parse, reproject, measure, and persist geospatial file contents.
    Tracks exact per-feature latency and total processing duration.
    """
    t_file_start = time.perf_counter()
    file_path = Path(file_path_str)
    close_db_on_exit = False
    if db is None:
        db = SessionLocal()
        close_db_on_exit = True
    try:
        file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
        if not file_record:
            logger.error("FileRecord with id %s not found in database.", file_id)
            return

        parser = get_parser(file_path)
        dataset = parser.parse(file_path)

        file_record.crs = dataset.crs
        file_record.feature_count = dataset.feature_count

        feature_records: list[FeatureRecord] = []
        for feature in dataset.features:
            t_feat_start = time.perf_counter()
            measurements, proj_crs, notes = MeasurementService.calculate_measurements(
                feature.geometry, feature.crs
            )
            feat_duration_ms = round((time.perf_counter() - t_feat_start) * 1000, 3)
            geom_geojson = mapping(feature.geometry)

            feat_record = FeatureRecord(
                file_id=file_record.id,
                feature_index=feature.index,
                feature_identifier=feature.identifier,
                geometry_type=feature.geometry_type,
                geometry=geom_geojson,
                properties=feature.properties,
                original_crs=feature.crs,
                projected_crs=proj_crs,
                measurements=measurements,
                processing_time_ms=feat_duration_ms,
                notes=notes,
            )
            feature_records.append(feat_record)

        # Batch insert for high performance and scalability
        db.bulk_save_objects(feature_records)
        total_duration_ms = round((time.perf_counter() - t_file_start) * 1000, 2)
        file_record.processing_time_ms = total_duration_ms
        file_record.status = "COMPLETED"
        db.commit()
        logger.info(
            "Successfully processed file %s with %d features in %.2f ms.",
            file_id, len(feature_records), total_duration_ms
        )

    except Exception as e:
        logger.exception("Failed processing file %s: %s", file_id, str(e))
        db.rollback()
        try:
            file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
            if file_record:
                file_record.status = "FAILED"
                file_record.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        if close_db_on_exit:
            db.close()
