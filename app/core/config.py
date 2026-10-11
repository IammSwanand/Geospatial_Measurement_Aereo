from pathlib import Path
import os

class Settings:
    PROJECT_NAME: str = "AereoIO - Geospatial File Measurement API"
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api"
    
    # Base directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    
    # Storage settings
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
    TEMP_DIR: Path = BASE_DIR / "storage" / "temp"
    
    # Max file upload size in MB (default 100 MB for geospatial files)
    MAX_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS: set[str] = {".zip", ".kml"}
    
    # Database (stored inside storage/ to keep project root clean)
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'storage' / 'aereo_geo.db'}")
    
    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_UPLOADS_PER_MINUTE: int = 15

settings = Settings()

# Ensure storage directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
