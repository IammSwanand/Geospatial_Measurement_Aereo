import zipfile
import tempfile
from pathlib import Path
import fiona
from shapely.geometry import shape
from app.core.exceptions import InvalidGeospatialFileError
from app.services.parsers.base import BaseGeospatialParser, ParsedDataset, ParsedFeature
from app.services.crs_transformer import CRSTransformer

class ShapefileParser(BaseGeospatialParser):
    """
    Parser for ESRI Shapefiles bundled within .zip archives.
    Handles safe extraction, validation of components (.shp, .shx, .dbf, .prj),
    and feature extraction.
    """

    def parse(self, file_path: Path) -> ParsedDataset:
        if not zipfile.is_zipfile(file_path):
            raise InvalidGeospatialFileError("Uploaded file is not a valid ZIP archive.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Safe zip extraction guarding against Zip-Slip vulnerabilities
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        member_path = (temp_path / member).resolve()
                        if not str(member_path).startswith(str(temp_path.resolve())):
                            raise InvalidGeospatialFileError("Malicious ZIP archive path detected (Zip-Slip attempt).")
                    zip_ref.extractall(temp_path)
            except zipfile.BadZipFile as e:
                raise InvalidGeospatialFileError(f"Corrupted ZIP archive: {str(e)}")

            # Find .shp files
            shp_files = list(temp_path.rglob("*.shp"))
            if not shp_files:
                raise InvalidGeospatialFileError("No .shp file found within the provided ZIP archive.")

            shp_file = shp_files[0]
            stem = shp_file.stem
            parent = shp_file.parent

            # Verify associated component files
            if not (parent / f"{stem}.dbf").exists():
                raise InvalidGeospatialFileError("Shapefile is missing mandatory .dbf attribute table component.")

            try:
                with fiona.open(shp_file) as src:
                    crs_info = None
                    if hasattr(src, "crs") and src.crs:
                        crs_info = src.crs.to_string() if hasattr(src.crs, "to_string") else str(src.crs)
                    elif hasattr(src, "crs_wkt") and src.crs_wkt:
                        crs_info = src.crs_wkt
                    dataset_crs = CRSTransformer.normalize_crs(crs_info if crs_info else "EPSG:4326")

                    features: list[ParsedFeature] = []
                    for idx, feat in enumerate(src):
                        geom_dict = feat.get("geometry")
                        if not geom_dict:
                            continue
                        geom = shape(geom_dict)
                        raw_props = dict(feat.get("properties", {}))
                        clean_props = {}
                        for k, v in raw_props.items():
                            if v is None or isinstance(v, (str, int, float, bool)):
                                clean_props[k] = v
                            else:
                                clean_props[k] = str(v)

                        feat_id = str(getattr(feat, "id", None) if getattr(feat, "id", None) is not None else (feat.get("id") if isinstance(feat, dict) else idx))

                        features.append(
                            ParsedFeature(
                                index=idx,
                                identifier=feat_id,
                                geometry=geom,
                                geometry_type=geom.geom_type,
                                properties=clean_props,
                                crs=dataset_crs,
                            )
                        )

                    return ParsedDataset(
                        crs=dataset_crs,
                        features=features,
                        feature_count=len(features),
                    )
            except Exception as e:
                raise InvalidGeospatialFileError(f"Failed to read Shapefile: {str(e)}")
