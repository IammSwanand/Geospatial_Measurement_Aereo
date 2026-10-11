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
    Leverages zero-disk in-memory virtual filesystem (GDAL VSI) with graceful fallback
    to temporary directory extraction.
    """

    def parse(self, file_path: Path) -> ParsedDataset:
        if not zipfile.is_zipfile(file_path):
            raise InvalidGeospatialFileError("Uploaded file is not a valid ZIP archive.")

        # Inspect ZIP archive structure in-memory
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                shp_candidates = [
                    n for n in names
                    if n.lower().endswith(".shp") and not n.startswith("__MACOSX")
                ]
                if not shp_candidates:
                    raise InvalidGeospatialFileError("No .shp file found within the provided ZIP archive.")

                target_shp = shp_candidates[0]
                target_stem = Path(target_shp).stem.lower()
                dbf_found = any(
                    Path(n).stem.lower() == target_stem and n.lower().endswith(".dbf")
                    for n in names
                )
                if not dbf_found:
                    raise InvalidGeospatialFileError("Shapefile is missing mandatory .dbf attribute table component.")
        except InvalidGeospatialFileError:
            raise
        except zipfile.BadZipFile as e:
            raise InvalidGeospatialFileError(f"Corrupted ZIP archive: {str(e)}")

        # Fast path: Read directly via GDAL VSI without disk extraction
        posix_path = file_path.resolve().as_posix()
        vsi_uri = f"zip://{posix_path}!{target_shp}"
        try:
            with fiona.open(vsi_uri) as src:
                return self._extract_features_from_src(src)
        except Exception:
            pass

        # Fallback: Extract to temporary directory if VSI cannot read the archive
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            try:
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    for member in zip_ref.namelist():
                        member_path = (temp_path / member).resolve()
                        if not str(member_path).startswith(str(temp_path.resolve())):
                            raise InvalidGeospatialFileError("Malicious ZIP archive path detected (Zip-Slip attempt).")
                    zip_ref.extractall(temp_path)
            except zipfile.BadZipFile as e:
                raise InvalidGeospatialFileError(f"Corrupted ZIP archive: {str(e)}")

            shp_files = list(temp_path.rglob("*.shp"))
            if not shp_files:
                raise InvalidGeospatialFileError("No .shp file found within the provided ZIP archive.")

            shp_file = shp_files[0]
            try:
                with fiona.open(shp_file) as src:
                    return self._extract_features_from_src(src)
            except Exception as e:
                raise InvalidGeospatialFileError(f"Failed to read Shapefile: {str(e)}")

    def _extract_features_from_src(self, src) -> ParsedDataset:
        crs_info = None
        if hasattr(src, "crs") and src.crs:
            crs_info = src.crs.to_string() if hasattr(src.crs, "to_string") else str(src.crs)
        elif hasattr(src, "crs_wkt") and src.crs_wkt:
            crs_info = src.crs_wkt
        dataset_crs = CRSTransformer.normalize_crs(crs_info if crs_info else "EPSG:4326")

        features: list[ParsedFeature] = []
        for idx, feat in enumerate(src):
            geom_dict = getattr(feat, "geometry", None) or (feat.get("geometry") if isinstance(feat, dict) else None)
            if not geom_dict:
                continue
            geom = shape(geom_dict)
            raw_props = dict(getattr(feat, "properties", None) or (feat.get("properties") if isinstance(feat, dict) else {}))
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
