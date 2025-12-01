from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple


@dataclass
class AddressConfig:
    id: int
    region: str
    city: str
    street: str
    house: str
    label: str
    guild_id: int
    channel_id: int
    message_id: Optional[int] = None


@dataclass
class PowerStatus:
    address: AddressConfig
    current_status: str
    current_status_label: str
    next_change: Optional[str] = None
    next_change_status: Optional[str] = None
    schedule_blocks: Optional[List[Tuple[str, str, str]]] = None
    hourly_schedule: Optional[Dict[int, str]] = None
    last_update: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class ScheduleData:
    preset: Dict
    fact: Dict
    csrf_token: str
    cookie: str


class DTEKException(Exception):
    pass


class NetworkException(DTEKException):
    pass


class ParsingException(DTEKException):
    pass


class ValidationException(DTEKException):
    pass
