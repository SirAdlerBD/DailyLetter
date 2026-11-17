"""Pluggable data sources. Every source returns the same kind of facts for its topic."""

from .agenda_ical import IcalAgendaSource
from .base import Source, SourceResult, Window, collect
from .garmin_mcp import GarminMcpSource

# Topic -> source. Swapping a provider (another calendar, another watch) means
# adding a class here that returns the same facts for that topic.
DEFAULT_SOURCES: list[Source] = [IcalAgendaSource(), GarminMcpSource()]

__all__ = ["DEFAULT_SOURCES", "Source", "SourceResult", "Window", "collect"]
