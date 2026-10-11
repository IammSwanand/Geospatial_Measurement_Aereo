import zipfile
from pathlib import Path
from typing import BinaryIO
from app.core.exceptions import InvalidGeospatialFileError

# Maximum uncompressed size for a zip archive (250 MB)
MAX_UNCOMPRESSED_ZIP_BYTES = 250 * 1024 * 1024

# Maximum compression ratio threshold to prevent zip-bomb DoS
MAX_COMPRESSION_RATIO = 100.0

# Maximum number of files in a Shapefile archive
MAX_ZIP_FILE_COUNT = 50

# Whitelist of valid Shapefile components and standard companion metadata
ALLOWED_SHAPEFILE_EXTENSIONS = {
    # Core Shapefile components
    ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".sbn", ".sbx", ".fbn", ".fbx", ".ain",
    ".aih", ".ixs", ".mxs", ".atx", ".xml", ".qix",
    # Standard companion documentation and metadata in public GIS releases (e.g. Natural Earth)
    ".html", ".htm", ".txt", ".md", ".csv", ".json", ".rst", ".pdf"
}

# Blacklist of executable and script extensions
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".ps1", ".vbs",
    ".dll", ".so", ".pyd", ".py", ".pyc", ".php", ".phtml",
    ".asp", ".aspx", ".jsp", ".js", ".jar", ".war", ".bin",
    ".scr", ".msi", ".com", ".hta", ".wsf"
}

# Magic bytes headers for ZIP archives
ZIP_MAGIC_HEADERS = [
    b"PK\x03\x04",  # Standard zip
    b"PK\x05\x06",  # Empty zip
    b"PK\x07\x08",  # Spanned zip
]

# Prohibited XML elements for preventing XXE and Billion Laughs DoS
PROHIBITED_XML_PATTERNS = [
    b"<!DOCTYPE",
    b"<!ENTITY",
]

def validate_magic_bytes(header: bytes, expected_suffix: str) -> None:
    """
    Verifies that the file content matches its declared format via magic bytes.
    Prevents content spoofing (e.g. uploading an executable renamed as .zip or .kml).
    """
    if expected_suffix == ".zip":
        if not any(header.startswith(magic) for magic in ZIP_MAGIC_HEADERS):
            raise InvalidGeospatialFileError(
                "File signature verification failed: File has .zip extension but does not contain a valid ZIP header."
            )
    elif expected_suffix == ".kml":
        # Check for binary executables spoofed as KML
        if header.startswith(b"MZ") or header.startswith(b"\x7fELF") or header.startswith(b"\xca\xfe\xba\xbe"):
            raise InvalidGeospatialFileError(
                "File signature verification failed: Binary executable disguised as KML file."
            )
        # Verify text/XML format (allowing UTF-8 BOM and leading whitespace)
        stripped = header.lstrip(b"\xef\xbb\xbf \t\r\n")
        header_lower = header.lower()
        if not (stripped.startswith(b"<") or b"<?xml" in header_lower or b"<kml" in header_lower or b"<document" in header_lower):
            raise InvalidGeospatialFileError(
                "File signature verification failed: File is not a valid text-based XML/KML document."
            )

def validate_kml_security(file_path: Path) -> None:
    """
    Scans KML file to prevent XML External Entity (XXE) and XML Entity Expansion (Billion Laughs) attacks.
    """
    try:
        # Read the first 64KB where DTD and DOCTYPE declarations reside
        with file_path.open("rb") as f:
            chunk = f.read(65536)

        chunk_upper = chunk.upper()
        for pattern in PROHIBITED_XML_PATTERNS:
            if pattern in chunk_upper:
                raise InvalidGeospatialFileError(
                    f"Malicious XML payload detected: Use of '{pattern.decode()}' is forbidden to prevent XXE / DoS attacks."
                )
    except InvalidGeospatialFileError:
        raise
    except Exception as e:
        raise InvalidGeospatialFileError(f"Security validation failed on KML file: {str(e)}")

def validate_zip_security(file_path: Path) -> None:
    """
    Enforces strict security checks on ZIP archives:
    1. Zip-Bomb prevention (uncompressed size limit & compression ratio check).
    2. File count threshold (blocks archives with excessive files).
    3. Strict extension whitelist (ensures only Shapefile components are present).
    4. Rejection of dangerous executable/script extensions.
    5. Path traversal / Zip-Slip prevention.
    """
    if not zipfile.is_zipfile(file_path):
        raise InvalidGeospatialFileError("Uploaded file is not a valid ZIP archive.")

    compressed_size = file_path.stat().st_size
    total_uncompressed_size = 0

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            infolist = zf.infolist()

            if len(infolist) == 0:
                raise InvalidGeospatialFileError("ZIP archive is empty.")

            if len(infolist) > MAX_ZIP_FILE_COUNT:
                raise InvalidGeospatialFileError(
                    f"ZIP archive contains {len(infolist)} entries, exceeding the maximum allowed limit of {MAX_ZIP_FILE_COUNT} files."
                )

            for member in infolist:
                member_name = member.filename
                
                # Check for path traversal characters
                if ".." in member_name or member_name.startswith("/") or member_name.startswith("\\"):
                    raise InvalidGeospatialFileError(
                        f"Zip-Slip vulnerability detected: Member path '{member_name}' contains illegal directory traversal sequences."
                    )

                # Skip directories
                if member.is_dir() or member_name.endswith("/"):
                    continue

                member_suffix = Path(member_name).suffix.lower()

                # Block dangerous executable files
                if member_suffix in DANGEROUS_EXTENSIONS:
                    raise InvalidGeospatialFileError(
                        f"Malicious file detected: ZIP archive contains forbidden executable/script file '{member_name}'."
                    )

                # Whitelist: Only permit valid Shapefile component files
                if member_suffix not in ALLOWED_SHAPEFILE_EXTENSIONS:
                    raise InvalidGeospatialFileError(
                        f"Untrusted file in archive: '{member_name}' has extension '{member_suffix}' which is not a recognized Shapefile component."
                    )

                total_uncompressed_size += member.file_size

                # Check uncompressed size limit
                if total_uncompressed_size > MAX_UNCOMPRESSED_ZIP_BYTES:
                    raise InvalidGeospatialFileError(
                        f"Zip-Bomb detected: Total uncompressed size exceeds maximum allowed threshold of {int(MAX_UNCOMPRESSED_ZIP_BYTES / (1024 * 1024))}MB."
                    )

            # Check compression ratio
            if compressed_size > 0:
                ratio = total_uncompressed_size / compressed_size
                if ratio > MAX_COMPRESSION_RATIO:
                    raise InvalidGeospatialFileError(
                        f"Zip-Bomb detected: Suspicious compression ratio ({ratio:.1f}x) exceeds safety limit of {MAX_COMPRESSION_RATIO}x."
                    )

    except InvalidGeospatialFileError:
        raise
    except zipfile.BadZipFile as e:
        raise InvalidGeospatialFileError(f"Corrupted or malformed ZIP archive: {str(e)}")
    except Exception as e:
        raise InvalidGeospatialFileError(f"Security validation failed on ZIP archive: {str(e)}")
