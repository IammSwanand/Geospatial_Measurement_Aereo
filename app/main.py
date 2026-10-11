from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.exceptions import GeospatialError, InvalidGeospatialFileError, UnsupportedFileFormatError
from app.db.session import init_db
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist
    init_db()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="High-performance, scalable API for uploading, processing, and measuring geospatial Shapefiles and KML files.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Domain exception handlers
@app.exception_handler(InvalidGeospatialFileError)
async def invalid_file_handler(request: Request, exc: InvalidGeospatialFileError):
    return JSONResponse(
        status_code=400,
        content={"error": "InvalidGeospatialFile", "detail": str(exc)},
    )

@app.exception_handler(UnsupportedFileFormatError)
async def unsupported_format_handler(request: Request, exc: UnsupportedFileFormatError):
    return JSONResponse(
        status_code=400,
        content={"error": "UnsupportedFileFormat", "detail": str(exc)},
    )

@app.exception_handler(GeospatialError)
async def geospatial_error_handler(request: Request, exc: GeospatialError):
    return JSONResponse(
        status_code=500,
        content={"error": "GeospatialProcessingError", "detail": str(exc)},
    )

# Include API router under /api
app.include_router(api_router, prefix="/api")

@app.get("/", tags=["Root"])
def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "documentation": "/docs",
        "endpoints": {
            "upload_file": "POST /api/files/",
            "get_file_info": "GET /api/files/{id}/",
            "get_file_measurements": "GET /api/files/{id}/measurements/",
            "list_files": "GET /api/files/",
            "health_check": "GET /api/health",
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
