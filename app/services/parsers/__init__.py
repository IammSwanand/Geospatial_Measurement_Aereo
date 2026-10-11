from pathlib import Path
from app.core.exceptions import UnsupportedFileFormatError
from app.services.parsers.base import BaseGeospatialParser, ParsedDataset, ParsedFeature
from app.services.parsers.shapefile_parser import ShapefileParser
from app.services.parsers.kml_parser import KMLParser

def get_parser(filename_or_path: str | Path) -> BaseGeospatialParser:
    path = Path(filename_or_path)
    suffix = path.suffix.lower()

    if suffix == ".zip":
        return ShapefileParser()
    elif suffix == ".kml":
        return KMLParser()
    else:
        raise UnsupportedFileFormatError(
            f"Unsupported file format '{suffix}'. Supported formats are: .zip (Shapefile) and .kml"
        )

__all__ = ["BaseGeospatialParser", "ParsedDataset", "ParsedFeature", "ShapefileParser", "KMLParser", "get_parser"]
