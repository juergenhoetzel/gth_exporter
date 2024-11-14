from dataclasses import dataclass


@dataclass
class Gth:
    alias: str
    address: str
    rssi: int
    temp_celsius: float
    humidity_percent: float
    battery_percent: int
