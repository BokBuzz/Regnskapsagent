"""Databasetilgang (psycopg 3). Hver forespørsel kjører i én transaksjon med
riktig databaserolle og bruker-ID satt, slik at RLS gjelder."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

Conn = psycopg.Connection


class Database:
    def __init__(self, url: str, role: str, max_size: int = 10) -> None:
        self.role = role
        self.pool = ConnectionPool(
            url,
            min_size=1,
            max_size=max_size,
            configure=self._configure,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )

    def _configure(self, conn: Conn) -> None:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(self.role)))
        conn.execute("SET TIME ZONE 'Europe/Oslo'")
        conn.commit()

    @contextmanager
    def tx(self, user_id: UUID | None = None) -> Iterator[Conn]:
        with self.pool.connection() as conn:
            with conn.transaction():
                if user_id is not None:
                    conn.execute("select set_config('app.user_id', %s, true)", [str(user_id)])
                yield conn

    def close(self) -> None:
        self.pool.close()
