from dataclasses import dataclass


@dataclass
class Activity:
    order: int
    name: str
    url: str
    mod_type: str


@dataclass
class Section:
    index: int
    title: str
    node_html: str
    activities: list[Activity]
