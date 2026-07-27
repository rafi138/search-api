"""Geocoding search query (broader recall via fuzziness)."""
from .common import build_function_score, build_should, is_address_query, digit_must, all_words_must


def build_search_query(q: str, *, limit: int = 10, lat=None, lon=None,
                       zoom: int = 12, scale: float = 0.4, from_: int = 0,
                       bbox: str | None = None, radius=None) -> dict:
    return build_function_score(build_should(q, fuzzy=True), limit=limit, lat=lat, lon=lon,
                                zoom=zoom, scale=scale, from_=from_, bbox=bbox, radius=radius,
                                address_mode=is_address_query(q), must=digit_must(q),
                                all_words=all_words_must(q))
