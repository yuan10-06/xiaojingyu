"""天气：Open-Meteo 免费接口，结果写入心情。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .db import Store

WMO = {
    0: ("晴", 4.0),
    1: ("基本晴", 3.0),
    2: ("多云", 0.5),
    3: ("阴", -1.5),
    45: ("有雾", -2.0),
    48: ("雾凇", -2.0),
    51: ("小毛毛雨", -3.0),
    53: ("毛毛雨", -4.0),
    55: ("大毛毛雨", -5.0),
    61: ("小雨", -4.0),
    63: ("中雨", -6.0),
    65: ("大雨", -8.0),
    71: ("小雪", -2.0),
    73: ("中雪", -3.0),
    75: ("大雪", -4.0),
    80: ("阵雨", -5.0),
    81: ("强阵雨", -7.0),
    82: ("暴雨", -9.0),
    95: ("打雷", -8.0),
    96: ("雷阵雨伴冰雹", -9.0),
    99: ("强雷暴", -10.0),
}


@dataclass
class Weather:
    city: str
    temp: float
    feels: float
    text: str
    humidity: float
    wind: float
    delta: float
    ts: float

    def line(self) -> str:
        return f"{self.city}现在{self.text}，{self.temp:.0f}℃，体感{self.feels:.0f}℃，湿度{self.humidity:.0f}%"

    def hint(self) -> str:
        """给提示词的一句话影响。"""
        if self.delta <= -6:
            return "天气很糟，你心情被压着，会想窝着、也会想找他说两句。"
        if self.delta >= 3:
            return "天气不错，你心情轻快，话会比平时多。"
        return "天气一般，对你影响不大。"


class WeatherService:
    def __init__(self, store: Store, cfg: dict[str, Any]):
        self.store = store
        self.cfg = cfg
        self.city = cfg.get("city", "郑州")
        self.lat = cfg.get("lat")
        self.lon = cfg.get("lon")
        self.refresh = float(cfg.get("refresh_minutes", 40)) * 60
        self._cache: Weather | None = None

    async def _geocode(self) -> tuple[float, float]:
        if self.lat is not None and self.lon is not None:
            return float(self.lat), float(self.lon)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": self.city, "count": 1, "language": "zh", "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results") or []
        if not results:
            raise RuntimeError(f"找不到城市：{self.city}")
        self.lat, self.lon = results[0]["latitude"], results[0]["longitude"]
        return float(self.lat), float(self.lon)

    async def get(self, force: bool = False) -> Weather | None:
        cached = self.store.get_state("weather_cache")
        if cached and not force and time.time() - cached.get("ts", 0) < self.refresh:
            return Weather(**{k: cached[k] for k in Weather.__annotations__})
        try:
            lat, lon = await self._geocode()
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                        "timezone": "Asia/Shanghai",
                    },
                )
                resp.raise_for_status()
                current = resp.json()["current"]
            code = int(current.get("weather_code", 0))
            text, delta = WMO.get(code, ("天气怪怪的", 0.0))
            temp = float(current.get("temperature_2m", 20))
            if temp >= 35:
                delta -= 5
            elif temp <= 3:
                delta -= 3
            elif 18 <= temp <= 26 and delta >= 0:
                delta += 1.5
            w = Weather(
                city=self.city,
                temp=temp,
                feels=float(current.get("apparent_temperature", temp)),
                text=text,
                humidity=float(current.get("relative_humidity_2m", 50)),
                wind=float(current.get("wind_speed_10m", 0)),
                delta=delta,
                ts=time.time(),
            )
            self.store.set_state("weather_cache", w.__dict__)
            self._cache = w
            return w
        except Exception:
            if cached:
                return Weather(**{k: cached[k] for k in Weather.__annotations__})
            return None
