class GeospatialError(Exception):
    """Base exception for geospatial operations."""
    pass

class UnsupportedFileFormatError(GeospatialError):
    """Raised when uploaded file format is not supported."""
    pass

class InvalidGeospatialFileError(GeospatialError):
    """Raised when geospatial file is corrupt or missing mandatory components."""
    pass

class CRSProjectionError(GeospatialError):
    """Raised when coordinate reference system projection transformation fails."""
    pass
