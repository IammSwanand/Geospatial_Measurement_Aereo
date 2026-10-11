from typing import Optional, Dict, Any, Tuple
from shapely.geometry.base import BaseGeometry
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint
from app.services.crs_transformer import CRSTransformer

class MeasurementService:
    """
    Computes accurate metric measurements for supported geometries.
    Always reprojects geographic coordinates to a projected planar CRS before calculation.
    Gracefully handles points and unsupported geometry types without crashing.
    """

    @classmethod
    def calculate_measurements(
        cls, geometry: BaseGeometry, original_crs: str
    ) -> Tuple[Optional[Dict[str, float]], Optional[str], Optional[str]]:
        """
        Calculates measurements for a geometry.
        Returns:
            Tuple[measurements_dict, projected_crs_name, notes_str]
        """
        if geometry is None or geometry.is_empty:
            return None, None, "Geometry is empty or null."

        geom_type = geometry.geom_type

        # 1. Point / MultiPoint - explicit PDF requirement: "No measurement is required"
        if isinstance(geometry, (Point, MultiPoint)):
            return None, None, "Point geometry does not require measurement calculation."

        # 2. Polygon / MultiPolygon -> Area calculation
        if isinstance(geometry, (Polygon, MultiPolygon)):
            try:
                projected_geom, proj_crs = CRSTransformer.reproject_to_projected_crs(geometry, original_crs)
                area_sq_m = float(projected_geom.area)
                
                measurements = {
                    "area_sq_m": round(area_sq_m, 2),
                    "area_hectares": round(area_sq_m / 10_000.0, 4),
                    "area_sq_km": round(area_sq_m / 1_000_000.0, 6),
                }
                return measurements, proj_crs, None
            except Exception as e:
                return None, None, f"Error calculating area: {str(e)}"

        # 3. LineString / MultiLineString -> Length calculation
        if isinstance(geometry, (LineString, MultiLineString)):
            try:
                projected_geom, proj_crs = CRSTransformer.reproject_to_projected_crs(geometry, original_crs)
                length_m = float(projected_geom.length)

                measurements = {
                    "length_m": round(length_m, 2),
                    "length_km": round(length_m / 1_000.0, 4),
                }
                return measurements, proj_crs, None
            except Exception as e:
                return None, None, f"Error calculating length: {str(e)}"

        # 4. GeometryCollection or other unsupported types -> Graceful fallback
        return None, None, f"Geometry type '{geom_type}' is not supported for measurement calculation."
