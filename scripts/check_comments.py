import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ALLOWED = re.compile(r"#\s*(noqa|type:\s*ignore|pragma)")
SKIPPED_DIRS = {".venv", "node_modules", "__pycache__"}


def python_files(roots: list[str]) -> list[Path]:
    files = []
    for root in roots:
        for path in Path(root).rglob("*.py"):
            if not SKIPPED_DIRS.intersection(path.parts):
                files.append(path)
    return files


def find_comments(path: Path) -> list[str]:
    source = path.read_text()
    problems = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        line = token.start[0]
        if line == 1 and token.string.startswith("#!"):
            continue
        if not ALLOWED.match(token.string):
            problems.append(f"{path}:{line}: {token.string}")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if ast.get_docstring(node, clean=False) is not None:
                problems.append(f"{path}:{getattr(node, 'lineno', 1)}: docstring")
    return problems


def main() -> int:
    problems = [p for path in python_files(sys.argv[1:] or ["."]) for p in find_comments(path)]
    if problems:
        print("\n".join(problems))
        print(f"Комментарии в коде запрещены: {len(problems)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
