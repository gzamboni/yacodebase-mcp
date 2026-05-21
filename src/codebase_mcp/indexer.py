import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PointStruct

from .ast_chunker import chunk_file_ast
from .settings import get_settings
from .store import (
    add_repo,
    ensure_collection,
    get_client,
    get_repo_id,
    load_config,
    load_file_hashes,
    save_config,
    save_file_hashes,
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
MAX_CHUNK_CHARS = 16_000  # 8192 token limit; dense code ~2 chars/token → 16k chars safe


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
                "symbol_name": None,
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
                "symbol_name": None,
            }
        )
    return chunks


def chunk_file(content: str, filepath: str, repo_path: str) -> list[dict]:
    try:
        chunks = chunk_file_ast(content, filepath, repo_path)
    except Exception:
        chunks = None
    return chunks if chunks else _chunk_file_lines(content, filepath, repo_path)


def _embed_batch(texts: list[str], client: OpenAI, model: str) -> list[list[float]]:
    for attempt in range(3):
        try:
            response = client.embeddings.create(
                model=model,
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
    settings = get_settings()
    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)
    qdrant = get_client()

    all_chunks: list[dict] = []
    for filepath in iter_files(Path(abs_path)):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel_path = str(filepath.relative_to(abs_path))
        all_chunks.extend(chunk_file(content, rel_path, abs_path))
    for c in all_chunks:
        c["text"] = c["text"][:MAX_CHUNK_CHARS]
    all_chunks = [c for c in all_chunks if c["text"].strip()]

    ensure_collection(qdrant, repo_id, vector_size=settings.vector_size)

    point_id = 0
    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        embeddings = _embed_batch(
            [c["text"] for c in batch], openai_client, settings.embedding_model
        )
        points = [
            PointStruct(id=point_id + j, vector=emb, payload=chunk)
            for j, (chunk, emb) in enumerate(zip(batch, embeddings))
        ]
        qdrant.upsert(collection_name=repo_id, points=points)
        point_id += len(batch)

    add_repo(abs_path, len(all_chunks))
    return len(all_chunks)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_repo_incremental(repo_path: str) -> int:
    """Index only changed/new files. Returns count of newly indexed chunks."""
    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    settings = get_settings()
    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)
    qdrant = get_client()

    stored_hashes = load_file_hashes(abs_path)
    current_hashes: dict[str, str] = {}
    changed_files: list[Path] = []
    deleted_rel_paths: list[str] = []

    current_rel_paths: set[str] = set()
    for filepath in iter_files(Path(abs_path)):
        rel = str(filepath.relative_to(abs_path))
        current_rel_paths.add(rel)
        sha = _file_sha256(filepath)
        current_hashes[rel] = sha
        if stored_hashes.get(rel) != sha:
            changed_files.append(filepath)

    for rel in stored_hashes:
        if rel not in current_rel_paths:
            deleted_rel_paths.append(rel)

    if not qdrant.collection_exists(collection_name=repo_id):
        ensure_collection(qdrant, repo_id, vector_size=settings.vector_size)

    files_to_clear = [str(f.relative_to(abs_path)) for f in changed_files] + deleted_rel_paths
    for rel in files_to_clear:
        try:
            qdrant.delete(
                collection_name=repo_id,
                points_selector=FilterSelector(
                    filter=Filter(must=[FieldCondition(key="file", match=MatchValue(value=rel))])
                ),
            )
        except Exception:
            pass

    all_new_chunks: list[dict] = []
    for filepath in changed_files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = str(filepath.relative_to(abs_path))
        all_new_chunks.extend(chunk_file(content, rel, abs_path))

    for c in all_new_chunks:
        c["text"] = c["text"][:MAX_CHUNK_CHARS]
    all_new_chunks = [c for c in all_new_chunks if c["text"].strip()]

    for i in range(0, len(all_new_chunks), BATCH_SIZE):
        batch = all_new_chunks[i : i + BATCH_SIZE]
        embeddings = _embed_batch(
            [c["text"] for c in batch], openai_client, settings.embedding_model
        )
        points = [
            PointStruct(id=str(uuid.uuid4()), vector=emb, payload=chunk)
            for chunk, emb in zip(batch, embeddings)
        ]
        qdrant.upsert(collection_name=repo_id, points=points)

    config = load_config()
    if abs_path in config:
        config[abs_path]["last_indexed"] = datetime.now(timezone.utc).isoformat()
        save_config(config)
    else:
        add_repo(abs_path, len(all_new_chunks))

    save_file_hashes(abs_path, current_hashes)

    return len(all_new_chunks)
