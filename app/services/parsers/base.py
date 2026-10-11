from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from shapely.geometry.base import BaseGeometry

@dataclass
class ParsedFeature:
    index: int
    identifier: str
    geometry: BaseGeometry
    geometry_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    crs: str = "EPSG:4326"

@dataclass
class ParsedDataset:
    crs: str
    features: List[ParsedFeature]
    feature_count: int

class BaseGeospatialParser(ABC):
    """Abstract base class for geospatial file parsers."""

    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDataset:
        """Parses a geospatial file and returns a standardized ParsedDataset."""
        pass
