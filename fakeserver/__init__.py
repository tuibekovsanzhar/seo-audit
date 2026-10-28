"""Local fake websites for testing the Maya crawler without touching the internet."""

from .server import FakeServer, RequestSeen, Response, Site
from .scenarios import SCENARIOS, Scenario

__all__ = ["FakeServer", "RequestSeen", "Response", "Site", "SCENARIOS", "Scenario"]
