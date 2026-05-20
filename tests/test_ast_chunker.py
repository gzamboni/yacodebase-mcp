import pytest

from codebase_mcp import ast_chunker


@pytest.fixture(autouse=True)
def clear_parser_cache():
    ast_chunker._parsers.clear()
    yield
    ast_chunker._parsers.clear()


# ── Fixtures ──────────────────────────────────────────────────────────────────

PYTHON_FUNCTIONS = """\
def greet(name: str) -> str:
    return f"Hello, {name}"


def farewell(name: str) -> str:
    return f"Goodbye, {name}"
"""

PYTHON_DECORATED = """\
def decorator(fn):
    return fn


@decorator
def annotated() -> None:
    pass
"""

PYTHON_ONLY_IMPORTS = """\
import os
import sys
from pathlib import Path
"""

TYPESCRIPT_CLASS = """\
class UserService {
    getUser(id: number): string {
        return `user-${id}`;
    }

    createUser(name: string): string {
        return `created-${name}`;
    }
}
"""

GO_FUNCTIONS = """\
package math

func Add(a, b int) int {
    return a + b
}

func Subtract(a, b int) int {
    return a - b
}
"""

RUST_FUNCTIONS = """\
fn add(a: i32, b: i32) -> i32 {
    a + b
}

struct Calculator;

impl Calculator {
    fn multiply(&self, a: i32, b: i32) -> i32 {
        a * b
    }
}
"""

JAVA_CLASS = """\
public class MathUtils {
    public MathUtils() {}

    public int add(int a, int b) {
        return a + b;
    }
}
"""

TERRAFORM_RESOURCES = """\
resource "aws_s3_bucket" "main" {
  bucket = "my-bucket"
}

resource "aws_instance" "web" {
  ami           = "ami-123456"
  instance_type = "t2.micro"
}
"""

# ── Tests ──────────────────────────────────────────────────────────────────────


def test_python_extracts_functions():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(PYTHON_FUNCTIONS, "foo.py", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    names = [c["text"].split("(")[0].split()[-1] for c in chunks]
    assert "greet" in names
    assert "farewell" in names


def test_python_extracts_decorated():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(PYTHON_DECORATED, "foo.py", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    # decorator def + decorated_definition = 2 nodes
    # only the decorated_definition wraps @decorator+def annotated
    func_chunks = [c for c in chunks if "annotated" in c["text"]]
    assert len(func_chunks) == 1
    assert func_chunks[0]["node_type"] == "decorated_definition"


def test_typescript_extracts_methods():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(TYPESCRIPT_CLASS, "svc.ts", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    texts = " ".join(c["text"] for c in chunks)
    assert "getUser" in texts
    assert "createUser" in texts
    # class itself must NOT be a chunk
    assert not any(c["text"].strip().startswith("class") for c in chunks)


def test_go_extracts_functions():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(GO_FUNCTIONS, "math.go", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    texts = " ".join(c["text"] for c in chunks)
    assert "Add" in texts
    assert "Subtract" in texts


def test_rust_extracts_functions():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(RUST_FUNCTIONS, "lib.rs", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    texts = " ".join(c["text"] for c in chunks)
    assert "fn add" in texts
    assert "fn multiply" in texts


def test_java_extracts_methods():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(JAVA_CLASS, "MathUtils.java", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    texts = " ".join(c["text"] for c in chunks)
    assert "MathUtils()" in texts  # constructor
    assert "add" in texts


def test_terraform_extracts_blocks():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(TERRAFORM_RESOURCES, "main.tf", "/repo")
    assert chunks is not None
    assert len(chunks) == 2
    texts = " ".join(c["text"] for c in chunks)
    assert "aws_s3_bucket" in texts
    assert "aws_instance" in texts


def test_unsupported_ext_returns_none():
    from codebase_mcp.ast_chunker import chunk_file_ast

    result = chunk_file_ast("key: value\n", "config.yaml", "/repo")
    assert result is None


def test_no_semantic_nodes_returns_none():
    from codebase_mcp.ast_chunker import chunk_file_ast

    result = chunk_file_ast(PYTHON_ONLY_IMPORTS, "imports.py", "/repo")
    assert result is None


def test_chunk_metadata():
    from codebase_mcp.ast_chunker import chunk_file_ast

    chunks = chunk_file_ast(PYTHON_FUNCTIONS, "src/foo.py", "/myrepo")
    assert chunks is not None
    c = chunks[0]
    assert c["file"] == "src/foo.py"
    assert c["repo_path"] == "/myrepo"
    assert isinstance(c["start_line"], int)
    assert isinstance(c["end_line"], int)
    assert c["start_line"] >= 1
    assert c["end_line"] >= c["start_line"]
    assert "node_type" in c


def test_chunk_file_falls_back_to_lines():
    from codebase_mcp.indexer import chunk_file

    content = "key: value\nanother: line\n"
    chunks = chunk_file(content, "config.yaml", "/repo")
    assert len(chunks) >= 1
    assert "node_type" not in chunks[0]
