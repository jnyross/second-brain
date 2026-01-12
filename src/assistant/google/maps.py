import logging
from dataclasses import dataclass
from typing import Any

import httpx

from assistant.config import settings

logger = logging.getLogger(__name__)

MAPS_BASE_URL = "https://maps.googleapis.com/maps/api"


@dataclass
class PlaceDetails:
    name: str
    address: str
    lat: float
    lng: float
    place_id: str
    place_type: str | None = None
    phone: str | None = None
    website: str | None = None

    @property
    def coordinates(self) -> tuple[float, float]:
        return (self.lat, self.lng)


@dataclass
class TravelTime:
    origin: str
    destination: str
    distance_meters: int
    duration_seconds: int
    duration_in_traffic_seconds: int | None = None

    @property
    def distance_km(self) -> float:
        return self.distance_meters / 1000

    @property
    def duration_minutes(self) -> int:
        return self.duration_seconds // 60

    @property
    def duration_with_traffic_minutes(self) -> int | None:
        if self.duration_in_traffic_seconds:
            return self.duration_in_traffic_seconds // 60
        return None

    def format_duration(self, include_traffic: bool = True) -> str:
        if include_traffic and self.duration_with_traffic_minutes:
            mins = self.duration_with_traffic_minutes
        else:
            mins = self.duration_minutes

        if mins < 60:
            return f"{mins} min"
        hours = mins // 60
        remaining = mins % 60
        if remaining == 0:
            return f"{hours} hr"
        return f"{hours} hr {remaining} min"


class MapsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.google_maps_api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def geocode(self, address: str) -> PlaceDetails | None:
        if not self.api_key:
            logger.warning("Google Maps API key not configured")
            return None

        client = await self._get_client()

        try:
            response = await client.get(
                f"{MAPS_BASE_URL}/geocode/json",
                params={"address": address, "key": self.api_key},
            )
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK" or not data.get("results"):
                logger.warning(f"Geocoding failed for '{address}': {data['status']}")
                return None

            result = data["results"][0]
            location = result["geometry"]["location"]

            place_type = None
            if result.get("types"):
                place_type = result["types"][0]

            return PlaceDetails(
                name=address,
                address=result["formatted_address"],
                lat=location["lat"],
                lng=location["lng"],
                place_id=result["place_id"],
                place_type=place_type,
            )
        except Exception as e:
            logger.error(f"Geocoding error for '{address}': {e}")
            return None

    async def search_place(self, query: str) -> PlaceDetails | None:
        if not self.api_key:
            logger.warning("Google Maps API key not configured")
            return None

        client = await self._get_client()

        try:
            response = await client.get(
                f"{MAPS_BASE_URL}/place/textsearch/json",
                params={"query": query, "key": self.api_key},
            )
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK" or not data.get("results"):
                logger.warning(f"Place search failed for '{query}': {data['status']}")
                return None

            result = data["results"][0]
            location = result["geometry"]["location"]

            return PlaceDetails(
                name=result.get("name", query),
                address=result.get("formatted_address", ""),
                lat=location["lat"],
                lng=location["lng"],
                place_id=result["place_id"],
                place_type=result.get("types", [None])[0],
            )
        except Exception as e:
            logger.error(f"Place search error for '{query}': {e}")
            return None

    async def get_place_details(self, place_id: str) -> PlaceDetails | None:
        if not self.api_key:
            return None

        client = await self._get_client()

        try:
            response = await client.get(
                f"{MAPS_BASE_URL}/place/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,formatted_address,geometry,formatted_phone_number,website,types",
                    "key": self.api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK":
                return None

            result = data["result"]
            location = result["geometry"]["location"]

            return PlaceDetails(
                name=result["name"],
                address=result.get("formatted_address", ""),
                lat=location["lat"],
                lng=location["lng"],
                place_id=place_id,
                place_type=result.get("types", [None])[0],
                phone=result.get("formatted_phone_number"),
                website=result.get("website"),
            )
        except Exception as e:
            logger.error(f"Place details error for '{place_id}': {e}")
            return None

    async def get_travel_time(
        self,
        origin: str | tuple[float, float],
        destination: str | tuple[float, float],
        mode: str = "driving",
    ) -> TravelTime | None:
        if not self.api_key:
            return None

        client = await self._get_client()

        origin_str = origin if isinstance(origin, str) else f"{origin[0]},{origin[1]}"
        dest_str = (
            destination if isinstance(destination, str) else f"{destination[0]},{destination[1]}"
        )

        try:
            params: dict[str, Any] = {
                "origins": origin_str,
                "destinations": dest_str,
                "mode": mode,
                "key": self.api_key,
            }

            if mode == "driving":
                params["departure_time"] = "now"

            response = await client.get(
                f"{MAPS_BASE_URL}/distancematrix/json",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK":
                logger.warning(f"Distance matrix failed: {data['status']}")
                return None

            element = data["rows"][0]["elements"][0]
            if element["status"] != "OK":
                logger.warning(f"Route not found: {element['status']}")
                return None

            duration_in_traffic = None
            if "duration_in_traffic" in element:
                duration_in_traffic = element["duration_in_traffic"]["value"]

            return TravelTime(
                origin=origin_str,
                destination=dest_str,
                distance_meters=element["distance"]["value"],
                duration_seconds=element["duration"]["value"],
                duration_in_traffic_seconds=duration_in_traffic,
            )
        except Exception as e:
            logger.error(f"Travel time error: {e}")
            return None

    async def enrich_place(self, place_name: str) -> PlaceDetails | None:
        place = await self.search_place(place_name)
        if place and place.place_id:
            detailed = await self.get_place_details(place.place_id)
            if detailed:
                return detailed
        return place
