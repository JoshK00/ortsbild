import json

import psycopg

from privacy.retry import retry
from research.models import ResearchResult
from research.registry import RegistryEntry, RegistryKey


class PostgresRegistryStore:
    """Keeps the memory of the research in the table `authority_registry` (see sql/postgres/006_research.sql)."""

    def __init__(self, dsn: str, connect=psycopg.connect) -> None:
        self.dsn = dsn
        self.connect = connect

    def find(self, key: RegistryKey) -> RegistryEntry | None:
        def run():
            with self.connect(self.dsn) as connection:
                return connection.execute(
                    "select result, confirmations, team_verified, updated_at from authority_registry "
                    "where country_code = %s and municipality = %s and category = %s",
                    (key.country_code, key.municipality, key.category),
                ).fetchone()

        row = retry(run, "registry read")
        if row is None:
            return None
        result = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return RegistryEntry(key, ResearchResult.model_validate(result), row[1], row[2], row[3])

    def save(self, key: RegistryKey, result: ResearchResult) -> None:
        from psycopg.types.json import Jsonb

        def run() -> None:
            with self.connect(self.dsn) as connection:
                connection.execute(
                    "insert into authority_registry (country_code, municipality, category, result) values (%s, %s, %s, %s) "
                    "on conflict (country_code, municipality, category) do update set result = excluded.result, updated_at = now()",
                    (key.country_code, key.municipality, key.category, Jsonb(result.model_dump(mode="json"))),
                )

        retry(run, "registry save")

    def forget(self, key: RegistryKey) -> None:
        def run() -> None:
            with self.connect(self.dsn) as connection:
                connection.execute(
                    "delete from authority_registry where country_code = %s and municipality = %s and category = %s",
                    (key.country_code, key.municipality, key.category),
                )

        retry(run, "registry delete")
