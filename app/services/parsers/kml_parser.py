import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from shapely.geometry import Polygon, LineString, Point, MultiPolygon, MultiLineString, GeometryCollection
from shapely.geometry.base import BaseGeometry
from app.core.exceptions import InvalidGeospatialFileError
from app.services.parsers.base import BaseGeospatialParser, ParsedDataset, ParsedFeature

class KMLParser(BaseGeospatialParser):
    """
    Robust pure-Python parser for Keyhole Markup Language (.kml) files.
    Parses Placemarks containing Polygons, LineStrings, Points, and MultiGeometries,
    extracting properties and coordinates according to the OGC KML 2.2 standard.
    """

    def parse(self, file_path: Path) -> ParsedDataset:
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise InvalidGeospatialFileError(f"Malformed or invalid KML file: {str(e)}")
        except Exception as e:
            raise InvalidGeospatialFileError(f"Could not read KML file: {str(e)}")

        features: List[ParsedFeature] = []
        feature_index = 0

        # Iterate over all Placemark elements regardless of XML namespace
        for elem in root.iter():
            tag = self._strip_namespace(elem.tag)
            if tag == "Placemark":
                parsed = self._parse_placemark(elem, feature_index)
                if parsed:
                    features.append(parsed)
                    feature_index += 1

        return ParsedDataset(
            crs="EPSG:4326",
            features=features,
            feature_count=len(features),
        )

    def _strip_namespace(self, tag: str) -> str:
        """Removes XML namespace prefix (e.g., '{http://www.opengis.net/kml/2.2}Placemark' -> 'Placemark')."""
        return tag.split("}")[-1] if "}" in tag else tag

    def _parse_placemark(self, placemark: ET.Element, index: int) -> Optional[ParsedFeature]:
        props: Dict[str, Any] = {}
        geom: Optional[BaseGeometry] = None
        placemark_id = placemark.get("id") or str(index)

        for child in placemark:
            tag = self._strip_namespace(child.tag)
            if tag == "name":
                props["name"] = child.text.strip() if child.text else ""
            elif tag == "description":
                props["description"] = child.text.strip() if child.text else ""
            elif tag == "ExtendedData":
                props.update(self._parse_extended_data(child))
            elif tag in ("Polygon", "LineString", "Point", "MultiGeometry"):
                geom = self._parse_geometry_element(child)

        if geom is None:
            return None

        return ParsedFeature(
            index=index,
            identifier=placemark_id,
            geometry=geom,
            geometry_type=geom.geom_type,
            properties=props,
            crs="EPSG:4326",
        )

    def _find_first(self, elem: ET.Element, target_tag: str) -> Optional[ET.Element]:
        """Finds first descendant element matching target_tag ignoring namespaces."""
        for child in elem.iter():
            if self._strip_namespace(child.tag) == target_tag:
                return child
        return None

    def _parse_extended_data(self, ext_elem: ET.Element) -> Dict[str, Any]:
        props = {}
        for child in ext_elem:
            tag = self._strip_namespace(child.tag)
            if tag == "Data":
                name = child.get("name")
                val_elem = self._find_first(child, "value")
                val = val_elem.text.strip() if val_elem is not None and val_elem.text else ""
                if name:
                    props[name] = val
            elif tag in ("SimpleData", "SchemaData"):
                name = child.get("name")
                if name:
                    props[name] = child.text.strip() if child.text else ""
        return props

    def _parse_coordinates(self, text: str) -> List[Tuple[float, float]]:
        """Parses KML coordinate string format: 'lon,lat,alt lon,lat,alt ...'"""
        coords: List[Tuple[float, float]] = []
        raw_tuples = text.strip().split()
        for raw in raw_tuples:
            parts = raw.split(",")
            if len(parts) >= 2:
                try:
                    lon = float(parts[0].strip())
                    lat = float(parts[1].strip())
                    coords.append((lon, lat))
                except ValueError:
                    continue
        return coords

    def _parse_geometry_element(self, elem: ET.Element) -> Optional[BaseGeometry]:
        tag = self._strip_namespace(elem.tag)

        if tag == "Point":
            coord_elem = self._find_first(elem, "coordinates")
            if coord_elem is not None and coord_elem.text:
                coords = self._parse_coordinates(coord_elem.text)
                if coords:
                    return Point(coords[0])

        elif tag == "LineString":
            coord_elem = self._find_first(elem, "coordinates")
            if coord_elem is not None and coord_elem.text:
                coords = self._parse_coordinates(coord_elem.text)
                if len(coords) >= 2:
                    return LineString(coords)

        elif tag == "Polygon":
            outer_ring_coords = []
            inner_rings_coords = []

            for child in elem:
                c_tag = self._strip_namespace(child.tag)
                if c_tag == "outerBoundaryIs":
                    c_elem = self._find_first(child, "coordinates")
                    if c_elem is not None and c_elem.text:
                        outer_ring_coords = self._parse_coordinates(c_elem.text)
                elif c_tag == "innerBoundaryIs":
                    c_elem = self._find_first(child, "coordinates")
                    if c_elem is not None and c_elem.text:
                        ring = self._parse_coordinates(c_elem.text)
                        if len(ring) >= 3:
                            inner_rings_coords.append(ring)

            if len(outer_ring_coords) >= 3:
                return Polygon(outer_ring_coords, inner_rings_coords)

        elif tag == "MultiGeometry":
            sub_geoms = []
            for child in elem:
                sub = self._parse_geometry_element(child)
                if sub is not None:
                    sub_geoms.append(sub)
            if not sub_geoms:
                return None
            
            # Group into MultiPolygon or MultiLineString if homogenous
            if all(isinstance(g, Polygon) for g in sub_geoms):
                return MultiPolygon(sub_geoms)
            if all(isinstance(g, LineString) for g in sub_geoms):
                return MultiLineString(sub_geoms)
            return GeometryCollection(sub_geoms)

        return None
