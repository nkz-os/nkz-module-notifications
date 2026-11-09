"""Module contribution contract (spec 7.1). Unknown fields are ignored; open vocabularies stay str."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Subject(_Base):
    type: str  # open: parcel|machine|facility|animal_group|farm|...
    id: str = ""
    name: str = ""


class When(_Base):
    type: Literal["today", "this_week", "date", "undated"]
    date: Optional[str] = None


class Text(_Base):
    title: str = ""
    why: str = ""


class Link(_Base):
    kind: str
    params: dict = {}


class Task(_Base):
    id: str
    subject: Subject
    kind: str  # open
    when: When
    text: dict[str, Text]
    link: Optional[Link] = None
    relatedAlertId: Optional[str] = None


class Change(_Base):
    subject: Subject
    text: dict[str, Text]
    link: Optional[Link] = None


class Metric(_Base):
    key: str
    value: Optional[float] = None
    origin: Literal["sensor", "estimated", "forecast"]


class Figure(_Base):
    subject: Subject
    metrics: list[Metric] = []


class Contribution(_Base):
    version: int
    complete: bool
    unknown_count: int = 0  # active-crop parcels with no recent assessment; absent means 0
    tasks: list[Task] = []
    changes: list[Change] = []
    figures: list[Figure] = []

    @classmethod
    def parse(cls, raw) -> "Contribution":
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("unsupported contribution version")
        return cls.model_validate(raw)
