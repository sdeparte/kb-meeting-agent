from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

import numpy as np

from kb_meeting_agent.models import Chunk

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

RRF_K = 60
AUTHORITATIVE_BOOST = 1.5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    headings TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT,
    verified_date TEXT,
    vector BLOB NOT NULL,
    start_line INTEGER,
    end_line INTEGER
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(body, tokenize = 'unicode61 remove_diacritics 2');
"""


def embedding_text(chunk: Chunk) -> str:
    if chunk.start_line is not None:
        return f"{chunk.anchor}\n{chunk.text}"
    return f"{chunk.path} > {' > '.join(chunk.headings)}\n{chunk.text}"


class SearchIndex:
    def __init__(self, path: Path, embed: Embedder) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(chunks)")}
        for column in ("start_line", "end_line"):
            if column not in columns:  # index files created before code repositories
                self._db.execute(f"ALTER TABLE chunks ADD COLUMN {column} INTEGER")
        self._db.commit()
        self._embed = embed
        self._vectors: tuple[list[int], np.ndarray] | None = None  # ids, normalised rows
        self._vectors_version = 0  # PRAGMA data_version they were loaded at

    def close(self) -> None:
        self._db.close()

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    def clear(self) -> None:
        self._vectors = None
        self._db.executescript("DELETE FROM files; DELETE FROM chunks; DELETE FROM chunks_fts;")
        self._db.commit()

    def file_hashes(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT path, hash FROM files"))

    def remove_file(self, path: str) -> None:
        self._vectors = None
        ids = [row[0] for row in self._db.execute("SELECT id FROM chunks WHERE path = ?", (path,))]
        self._db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
        self._db.execute("DELETE FROM chunks WHERE path = ?", (path,))
        self._db.execute("DELETE FROM files WHERE path = ?", (path,))
        self._db.commit()

    async def upsert_file(self, path: str, digest: str, chunks: list[Chunk]) -> None:
        texts = [embedding_text(chunk) for chunk in chunks]
        vectors = await self._embed(texts) if texts else []
        self.remove_file(path)
        for chunk, text, vector in zip(chunks, texts, vectors, strict=True):
            cursor = self._db.execute(
                "INSERT INTO chunks"
                "(path, headings, text, status, verified_date, vector, start_line, end_line) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.path,
                    json.dumps(list(chunk.headings), ensure_ascii=False),
                    chunk.text,
                    chunk.status,
                    chunk.verified_date,
                    np.asarray(vector, dtype=np.float32).tobytes(),
                    chunk.start_line,
                    chunk.end_line,
                ),
            )
            self._db.execute(
                "INSERT INTO chunks_fts(rowid, body) VALUES (?, ?)", (cursor.lastrowid, text)
            )
        self._db.execute("INSERT INTO files(path, hash) VALUES (?, ?)", (path, digest))
        self._db.commit()
        self._vectors = None

    async def search(self, query: str, k: int = 8, boost_paths: Iterable[str] = ()) -> list[Chunk]:
        lexical = self._lexical(query, limit=k * 4)
        [query_vector] = await self._embed([query])
        semantic = self._semantic(query_vector, limit=k * 4)
        scores: dict[int, float] = defaultdict(float)
        for ranking in (lexical, semantic):
            for rank, chunk_id in enumerate(ranking):
                scores[chunk_id] += 1 / (RRF_K + rank + 1)
        if not scores:
            return []
        rows = self._rows(list(scores))
        boosted = set(boost_paths)
        for chunk_id, row in rows.items():
            if row.path in boosted:
                scores[chunk_id] *= AUTHORITATIVE_BOOST
        # an id missing from rows was removed during the embedding await (a resync)
        top = sorted(rows, key=lambda chunk_id: scores[chunk_id], reverse=True)[:k]
        return [rows[chunk_id] for chunk_id in top]

    def section(self, path: str, headings: tuple[str, ...], text: str) -> list[Chunk]:
        """Every chunk of the section holding `text`, in page order: the chunks next to it with
        the same headings, not another section of the page that happens to share them."""
        key = json.dumps(list(headings), ensure_ascii=False)
        found = self._db.execute(
            "SELECT id FROM chunks WHERE path = ? AND headings = ? AND text = ? ORDER BY id",
            (path, key, text),
        ).fetchone()
        if found is None:
            return []
        page = self._db.execute(
            "SELECT id, headings FROM chunks WHERE path = ? ORDER BY id", (path,)
        ).fetchall()
        start = end = [chunk_id for chunk_id, _ in page].index(found[0])
        while start > 0 and page[start - 1][1] == key:
            start -= 1
        while end + 1 < len(page) and page[end + 1][1] == key:
            end += 1
        ids = [chunk_id for chunk_id, _ in page[start : end + 1]]
        rows = self._rows(ids)
        return [rows[chunk_id] for chunk_id in ids]

    def _lexical(self, query: str, limit: int) -> list[int]:
        terms = re.findall(r"\w+", query)
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in terms)
        return [
            row[0]
            for row in self._db.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, limit),
            )
        ]

    def _semantic(self, query_vector: list[float], limit: int) -> list[int]:
        # loaded once, until the index changes here or in another connection to the same file
        version = self._db.execute("PRAGMA data_version").fetchone()[0]
        if self._vectors is None or version != self._vectors_version:
            self._vectors_version = version
            rows = self._db.execute("SELECT id, vector FROM chunks").fetchall()
            if not rows:
                self._vectors = None
                return []
            matrix = np.stack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._vectors = ([row[0] for row in rows], matrix / np.where(norms == 0, 1.0, norms))
        ids, matrix = self._vectors
        query = np.asarray(query_vector, dtype=np.float32)
        similarities = matrix @ (query / (np.linalg.norm(query) or 1.0))
        order = np.argsort(-similarities)[:limit]
        return [ids[i] for i in order]

    def _rows(self, ids: list[int]) -> dict[int, Chunk]:
        placeholders = ",".join("?" * len(ids))
        result: dict[int, Chunk] = {}
        for chunk_id, path, headings, text, status, verified, start, end in self._db.execute(
            "SELECT id, path, headings, text, status, verified_date, start_line, end_line "
            "FROM chunks "
            f"WHERE id IN ({placeholders})",
            ids,
        ):
            result[chunk_id] = Chunk(
                path=path,
                headings=tuple(json.loads(headings)),
                text=text,
                status=status,
                verified_date=verified,
                start_line=start,
                end_line=end,
            )
        return result
