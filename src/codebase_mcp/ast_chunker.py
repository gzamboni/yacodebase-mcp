from __future__ import annotations

from pathlib import Path

MAX_CHUNK_CHARS = 32_000  # mirrors indexer.py constant

SEMANTIC_NODES: dict[str, set[str]] = {
    "python": {"function_definition", "decorated_definition"},
    "typescript": {"function_declaration", "method_definition", "arrow_function"},
    "typescript_tsx": {"function_declaration", "method_definition", "arrow_function"},
    "javascript": {"function_declaration", "method_definition", "arrow_function"},
    "go": {"function_declaration", "method_declaration"},
    "rust": {"function_item"},
    "java": {"method_declaration", "constructor_declaration"},
    "hcl": {"block"},
}

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript_tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".tf": "hcl",
}

_parsers: dict[str, object] = {}


def _get_parser(lang_name: str):
    if lang_name in _parsers:
        return _parsers[lang_name]

    try:
        from tree_sitter import Language, Parser

        if lang_name == "python":
            import tree_sitter_python as m

            lang = Language(m.language())
        elif lang_name == "typescript":
            import tree_sitter_typescript as m

            lang = Language(m.language_typescript())
        elif lang_name == "typescript_tsx":
            import tree_sitter_typescript as m

            lang = Language(m.language_tsx())
        elif lang_name == "javascript":
            import tree_sitter_javascript as m

            lang = Language(m.language())
        elif lang_name == "go":
            import tree_sitter_go as m

            lang = Language(m.language())
        elif lang_name == "rust":
            import tree_sitter_rust as m

            lang = Language(m.language())
        elif lang_name == "java":
            import tree_sitter_java as m

            lang = Language(m.language())
        elif lang_name == "hcl":
            import tree_sitter_hcl as m

            lang = Language(m.language())
        else:
            _parsers[lang_name] = None
            return None

        parser = Parser(lang)
        _parsers[lang_name] = parser
        return parser

    except ImportError:
        _parsers[lang_name] = None
        return None


def chunk_file_ast(content: str, filepath: str, repo_path: str) -> list[dict] | None:
    lang_name = EXT_TO_LANG.get(Path(filepath).suffix)
    if not lang_name:
        return None

    parser = _get_parser(lang_name)
    if parser is None:
        return None

    node_types = SEMANTIC_NODES[lang_name]
    tree = parser.parse(content.encode("utf-8", errors="replace"))

    chunks: list[dict] = []

    def walk(node) -> None:
        if node.type == "ERROR":
            return
        if node.type in node_types:
            text = content[node.start_byte : node.end_byte][:MAX_CHUNK_CHARS]
            chunks.append(
                {
                    "text": text,
                    "file": filepath,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "repo_path": repo_path,
                    "node_type": node.type,
                }
            )
            return  # don't descend — avoids nested method-inside-class duplication
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return chunks if chunks else None
