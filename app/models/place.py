"""Pydantic models for place endpoints.

Suggest/search return a *summary* (name + address + types + coordinates);
the place-details endpoint returns the full document. The public id is
``place_code`` (also the ES ``_id``).
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PlaceSummary(BaseModel):
    """Lightweight result for suggest & search."""
    model_config = ConfigDict(populate_by_name=True)

    place_code: Optional[str] = None
    name: str
    address: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # locality fields (always returned)
    city: Optional[str] = None
    area: Optional[str] = None
    postcode: Optional[str] = None
    district: Optional[str] = None
    sub_area: Optional[str] = None
    thana: Optional[str] = None
    sub_district: Optional[str] = None
    union: Optional[str] = None
    super_sub_area: Optional[str] = None
    # bangla fields (populated only when bangla=true)
    address_bn: Optional[str] = None
    city_bn: Optional[str] = None
    area_bn: Optional[str] = None

    @staticmethod
    def _coord(source: dict) -> tuple[Optional[float], Optional[float]]:
        gl = source.get("geo_location")
        if isinstance(gl, dict) and gl.get("lat") is not None and gl.get("lon") is not None:
            try:
                return float(gl["lat"]), float(gl["lon"])
            except (TypeError, ValueError):
                pass
        try:
            return float(source.get("latitude")), float(source.get("longitude"))
        except (TypeError, ValueError):
            return None, None

    @classmethod
    def from_source(cls, source: dict, bangla: bool = False) -> "PlaceSummary":
        name = (source.get("name") or source.get("business_name") or source.get("place_name")
                or (source.get("new_address") or "").split(",")[0].strip() or "")
        address = source.get("address") or source.get("new_address") or source.get("Address") or ""
        lat, lon = cls._coord(source)
        return cls(
            place_code=source.get("place_code") or source.get("uCode") or source.get("id"),
            name=name,
            address=address,
            type=source.get("pType") or source.get("type"),
            subtype=source.get("subType") or source.get("sub_type"),
            latitude=lat,
            longitude=lon,
            city=source.get("city"),
            area=source.get("area"),
            postcode=source.get("postCode"),
            district=source.get("district"),
            sub_area=source.get("sub_area"),
            thana=source.get("thana"),
            sub_district=source.get("sub_district"),
            union=source.get("union"),
            super_sub_area=source.get("super_sub_area"),
            address_bn=source.get("address_bn") if bangla else None,
            city_bn=source.get("city_bn") if bangla else None,
            area_bn=source.get("area_bn") if bangla else None,
        )


class PlaceDetail(BaseModel):
    """Full document (place details). ``extra=allow`` keeps all fields."""
    model_config = ConfigDict(extra="allow")

    place_code: Optional[str] = None
    name: Optional[str] = None
    alter_names: Optional[list[str]] = None
    business_name: Optional[str] = None
    place_name: Optional[str] = None
    new_address: Optional[str] = None
    address: Optional[str] = None
    address_bn: Optional[str] = None
    alternate_address: Optional[str] = None
    area: Optional[str] = None
    area_bn: Optional[str] = None
    city: Optional[str] = None
    city_bn: Optional[str] = None
    district: Optional[str] = None
    thana: Optional[str] = None
    union: Optional[str] = None
    sub_area: Optional[str] = None
    super_sub_area: Optional[str] = None
    postCode: Optional[Any] = None
    pType: Optional[str] = None
    subType: Optional[str] = None
    latitude: Optional[Any] = None
    longitude: Optional[Any] = None
    popularity_ranking: Optional[int] = None
    bounds: Optional[Any] = None
    location_shape: Optional[Any] = None


class SummaryResponse(BaseModel):
    places: list[PlaceSummary]
