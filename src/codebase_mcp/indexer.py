import os
import time
from pathlib import Path

from openai import OpenAI
from qdrant_client.models import PointStruct

from .ast_chunker import chunk_file_ast
from .store import (
    add_repo,
    ensure_collection,
    get_client,
    get_repo_id,
)

INDEXED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".tf",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
CHUNK_LINES = 100
OVERLAP_LINES = 20
MIN_LINES_FOR_SPLIT = 20
BATCH_SIZE = 100
MAX_CHUNK_CHARS = 32_000  # text-embedding-3-small limit is 8191 tokens (~4 chars/token)


def iter_files(repo_path: Path):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix in INDEXED_EXTENSIONS:
                yield filepath


def _chunk_file_lines(content: str, filepath: str, repo_path: str) -> list[dict]:
    lines = content.splitlines()
    if len(lines) < MIN_LINES_FOR_SPLIT:
        return [
            {
                "text": content[:MAX_CHUNK_CHARS],
                "file": filepath,
                "start_line": 1,
                "end_line": len(lines),
                "repo_path": repo_path,
            }
        ]

    chunks = []
    step = CHUNK_LINES - OVERLAP_LINES
    for i in range(0, len(lines), step):
        chunk_lines = lines[i : i + CHUNK_LINES]
        if not any(line.strip() for line in chunk_lines):
            continue
        text = "\n".join(chunk_lines)[:MAX_CHUNK_CHARS]
        chunks.append(
            {
                "text": text,
                "file": filepath,
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "repo_path": repo_path,
            }
        )
    return chunks


def chunk_file(content: str, filepath: str, repo_path: str) -> list[dict]:
    try:
        chunks = chunk_file_ast(content, filepath, repo_path)
    except Exception:
        chunks = None
    return chunks if chunks else _chunk_file_lines(content, filepath, repo_path)


def _embed_batch(texts: list[str], client: OpenAI) -> list[list[float]]:
    for attempt in range(3):
        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            return [r.embedding for r in response.data]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Embedding failed after 3 attempts")


def index_repo(repo_path: str) -> int:
    """Index a repo. Always replaces any existing index for this path."""
    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    openai_client = OpenAI()
    qdrant = get_client()

    all_chunks: list[dict] = []
    for filepath in iter_files(Path(abs_path)):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel_path = str(filepath.relative_to(abs_path))
        all_chunks.extend(chunk_file(content, rel_path, abs_path))

    ensure_collection(qdrant, repo_id)

    point_id = 0
    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        embeddings = _embed_batch([c["text"] for c in batch], openai_client)
        points = [
            PointStruct(id=point_id + j, vector=emb, payload=chunk)
            for j, (chunk, emb) in enumerate(zip(batch, embeddings))
        ]
        qdrant.upsert(collection_name=repo_id, points=points)
        point_id += len(batch)

    add_repo(abs_path, len(all_chunks))
    return len(all_chunks)
