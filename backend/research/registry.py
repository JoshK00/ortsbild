import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from research.models import ResearchResult

# An answer from the web is only trusted for this long, a contact can change
ENTRY_LIFETIME_DAYS = 30


def normalize(text: str) -> str:
    """The same place written differently ("München", "muenchen ", "MÜNCHEN") finds the same entry."""
    folded = unicodedata.normalize("NFKD", text.casefold().strip())
    return "".join(c for c in folded if not unicodedata.combining(c)).replace("ß", "ss")


@dataclass(frozen=True)
class RegistryKey:
    country_code: str
    municipality: str  # normalized
    category: str

    @classmethod
    def of(cls, country_code: str | None, municipality: str, category: str) -> "RegistryKey":
        return cls((country_code or "").upper(), normalize(municipality), category)


@dataclass(frozen=True)
class RegistryEntry:
    key: RegistryKey
    result: ResearchResult
    confirmations: int  # how many users confirmed it (0: only found by the agent)
    team_verified: bool  # a person of the team checked it
    updated_at: datetime

    def is_fresh(self, now: datetime | None = None) -> bool:
        """A verified entry does not expire, an entry that only the agent found does."""
        if self.team_verified:
            return True
        return (now or datetime.now(timezone.utc)) - self.updated_at < timedelta(days=ENTRY_LIFETIME_DAYS)


class RegistryStore(Protocol):
    """The memory of the research: what was found or confirmed for a place and a category."""

    def find(self, key: RegistryKey) -> RegistryEntry | None: ...

    def save(self, key: RegistryKey, result: ResearchResult) -> None:
        """Remember an answer found by the agent (confirmations 0). An entry that exists is only refreshed."""
        ...

    def forget(self, key: RegistryKey) -> None:
        """Drop an entry (the user said it is the wrong authority)."""
        ...


class InMemoryRegistryStore:
    """Keeps the entries in a dict. For tests and local experiments, nothing is persisted."""

    def __init__(self) -> None:
        self.entries: dict[RegistryKey, RegistryEntry] = {}

    def find(self, key: RegistryKey) -> RegistryEntry | None:
        return self.entries.get(key)

    def save(self, key: RegistryKey, result: ResearchResult) -> None:
        old = self.entries.get(key)
        self.entries[key] = RegistryEntry(
            key, result, old.confirmations if old else 0, old.team_verified if old else False, datetime.now(timezone.utc)
        )

    def forget(self, key: RegistryKey) -> None:
        self.entries.pop(key, None)


