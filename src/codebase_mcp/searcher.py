from pathlib import Path

from openai import OpenAI

from .settings import get_settings
from .store import get_client, load_config

TOP_K = 8


def search(query: str, repo_path: str | None = None) -> str:
    config = load_config()

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        if abs_path not in config:
            return f"Repo not indexed. Run: codebase-mcp index {repo_path}"
        candidates = {abs_path: config[abs_path]}
    else:
        if not config:
            return "No repos indexed. Run: codebase-mcp index /path/to/repo"
        candidates = config

    settings = get_settings()
    qdrant = get_client()
    warnings: list[str] = []
    valid_candidates: list[tuple[str, str]] = []  # (path, repo_id)

    for path, meta in candidates.items():
        repo_id = meta["repo_id"]
        try:
            info = qdrant.get_collection(repo_id)
            actual_size = info.config.params.vectors.size
        except Exception:
            continue
        if actual_size != settings.vector_size:
            warnings.append(
                f"⚠ Vector size mismatch for {path}: "
                f"indexed with {actual_size}, current model expects {settings.vector_size}. "
                f"Run: codebase-mcp reindex {path}"
            )
            continue
        valid_candidates.append((path, repo_id))

    warning_text = "\n".join(warnings)

    if not valid_candidates:
        return warning_text if warning_text else "No results found."

    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)

    response = openai_client.embeddings.create(
        model=settings.embedding_model,
        input=[query],
    )
    query_vector = response.data[0].embedding

    all_results = []
    for _path, repo_id in valid_candidates:
        try:
            results = qdrant.query_points(
                collection_name=repo_id,
                query=query_vector,
                limit=TOP_K,
            )
            all_results.extend(results.points)
        except Exception:
            continue

    if not all_results:
        return warning_text if warning_text else "No results found."

    all_results.sort(key=lambda r: r.score, reverse=True)
    top = all_results[:TOP_K]

    parts = []
    for r in top:
        p = r.payload
        parts.append(
            f"### {p['file']} (lines {p['start_line']}-{p['end_line']}) — score: {r.score:.3f}\n"
            f"```\n{p['text']}\n```"
        )
    result_text = "\n\n".join(parts)
    return f"{warning_text}\n\n{result_text}".strip() if warning_text else result_text
