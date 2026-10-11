import math
from functools import lru_cache
from typing import Tuple, Optional
import pyproj
from pyproj import CRS, Transformer
import shapely.ops
from shapely.geometry.base import BaseGeometry
from app.core.exceptions import CRSProjectionError

@lru_cache(maxsize=128)
def get_transformer(from_crs_str: str, to_crs_str: str) -> Transformer:
    """
    Cached creation of pyproj.Transformer.
    always_xy=True ensures (x, y) = (lon, lat) coordinates order.
    """
    return Transformer.from_crs(from_crs_str, to_crs_str, always_xy=True)

class CRSTransformer:
    """
    Handles Coordinate Reference System (CRS) inspection and reprojection.
    Ensures that geometries with geographic coordinates (e.g., EPSG:4326)
    are transformed into an appropriate metric projected coordinate system
    (such as dynamic UTM zone) before measurement calculations.
    """

    @staticmethod
    def normalize_crs(crs_input: Optional[str]) -> str:
        """Normalizes CRS string, defaulting to EPSG:4326 if not specified."""
        if not crs_input:
            return "EPSG:4326"
        crs_str = str(crs_input).strip()
        try:
            crs_obj = CRS.from_user_input(crs_str)
            # Return EPSG code if available, otherwise authority or WKT
            epsg = crs_obj.to_epsg()
            if epsg:
                return f"EPSG:{epsg}"
            auth = crs_obj.to_authority()
            if auth:
                return f"{auth[0]}:{auth[1]}"
            return crs_str
        except Exception:
            return crs_str

    @staticmethod
    def get_utm_epsg_for_coordinates(lon: float, lat: float) -> str:
        """
        Dynamically calculates the appropriate UTM EPSG code for a given longitude and latitude.
        - Northern Hemisphere: EPSG:32601 - EPSG:32660
        - Southern Hemisphere: EPSG:32701 - EPSG:32760
        - Polar regions (>84N or <-80S) use UPS North (EPSG:32661) / South (EPSG:32761)
        """
        # Clamp lon to [-180, 180]
        lon = ((lon + 180) % 360) - 180

        if lat > 84.0:
            return "EPSG:32661"  # UPS North
        elif lat < -80.0:
            return "EPSG:32761"  # UPS South

        zone = int(math.floor((lon + 180) / 6)) + 1
        zone = min(max(zone, 1), 60)

        if lat >= 0:
            return f"EPSG:{32600 + zone}"
        else:
            return f"EPSG:{32700 + zone}"

    @classmethod
    def get_optimal_projected_crs(cls, geometry: BaseGeometry, source_crs_str: str) -> str:
        """
        Determines the optimal metric projected CRS for a geometry.
        If source CRS is already a metric projected CRS (and not Web Mercator EPSG:3857 which
        severely distorts areas), it can be used directly.
        Otherwise, determines the local UTM zone based on geometry centroid.
        """
        try:
            source_crs = CRS.from_user_input(source_crs_str)
            if source_crs.is_projected:
                epsg = source_crs.to_epsg()
                # EPSG:3857 (Web Mercator) distorts area by up to 400% away from equator.
                # In that case, reproject to local UTM.
                if epsg != 3857:
                    return f"EPSG:{epsg}" if epsg else source_crs_str
        except Exception:
            pass

        # Calculate centroid in WGS84 coordinates to find UTM zone
        try:
            if source_crs_str.upper() not in ("EPSG:4326", "WGS84", "WGS 84"):
                # Transform to 4326 first to inspect lon/lat
                t_to_4326 = get_transformer(source_crs_str, "EPSG:4326")
                geom_4326 = shapely.ops.transform(t_to_4326.transform, geometry)
                centroid = geom_4326.centroid
            else:
                centroid = geometry.centroid

            return cls.get_utm_epsg_for_coordinates(centroid.x, centroid.y)
        except Exception as e:
            # Fallback to standard UTM 33N or World Cylindrical Equal Area
            return "EPSG:32633"

    @classmethod
    def reproject_to_projected_crs(
        cls, geometry: BaseGeometry, source_crs: str
    ) -> Tuple[BaseGeometry, str]:
        """
        Reprojects a geometry to an appropriate metric projected coordinate system.
        Returns:
            Tuple[projected_geometry, projected_crs_name]
        """
        if geometry.is_empty:
            return geometry, source_crs

        source_crs_normalized = cls.normalize_crs(source_crs)
        target_crs = cls.get_optimal_projected_crs(geometry, source_crs_normalized)

        if source_crs_normalized == target_crs:
            return geometry, target_crs

        try:
            transformer = get_transformer(source_crs_normalized, target_crs)
            projected_geom = shapely.ops.transform(transformer.transform, geometry)
            return projected_geom, target_crs
        except Exception as e:
            raise CRSProjectionError(
                f"Failed to transform geometry from {source_crs_normalized} to {target_crs}: {str(e)}"
            )
