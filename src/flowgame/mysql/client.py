"""MySQL connection pool for FlowGame databaseNode (env-based, no Nacos)."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from queue import Empty, Full, LifoQueue
from typing import Iterator, Optional

import pymysql
from pymysql.cursors import DictCursor

from src.flowgame.settings import get_flowgame_settings


class MySQLUtils:
    """Lightweight LifoQueue connection pool (singleton)."""

    _instance: Optional["MySQLUtils"] = None

    def __new__(cls) -> "MySQLUtils":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_size: int = 8, wait_timeout_sec: float = 5.0) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._max_size = max(1, int(max_size))
        self._wait_timeout_sec = max(0.1, float(wait_timeout_sec))
        self._pool: LifoQueue = LifoQueue(maxsize=self._max_size)
        self._created = 0
        self._lock = threading.Lock()

    def _build_connection(self) -> pymysql.connections.Connection:
        cfg = get_flowgame_settings()
        return pymysql.connect(
            host=cfg.mysql_host,
            port=cfg.mysql_port,
            user=cfg.mysql_user,
            password=cfg.mysql_password or None,
            database=cfg.mysql_database,
            charset=cfg.mysql_charset,
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=120,
            write_timeout=60,
            autocommit=True,
        )

    @staticmethod
    def _is_alive(conn: pymysql.connections.Connection) -> bool:
        try:
            conn.ping(reconnect=True)
            return True
        except Exception:
            return False

    def _decrease_created(self) -> None:
        with self._lock:
            self._created = max(0, self._created - 1)

    def acquire(self) -> pymysql.connections.Connection:
        try:
            conn = self._pool.get_nowait()
            if self._is_alive(conn):
                return conn
            try:
                conn.close()
            finally:
                self._decrease_created()
        except Empty:
            pass

        with self._lock:
            if self._created < self._max_size:
                self._created += 1
                try:
                    return self._build_connection()
                except Exception:
                    self._created -= 1
                    raise

        conn = self._pool.get(timeout=self._wait_timeout_sec)
        if self._is_alive(conn):
            return conn
        try:
            conn.close()
        finally:
            self._decrease_created()

        with self._lock:
            self._created += 1
            try:
                return self._build_connection()
            except Exception:
                self._created -= 1
                raise

    def release(self, conn: Optional[pymysql.connections.Connection]) -> None:
        if conn is None:
            return
        if not self._is_alive(conn):
            try:
                conn.close()
            finally:
                self._decrease_created()
            return
        try:
            self._pool.put_nowait(conn)
        except Full:
            try:
                conn.close()
            finally:
                self._decrease_created()

    @contextmanager
    def connection(self) -> Iterator[pymysql.connections.Connection]:
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)


mysql_utils = MySQLUtils()
