"""List every Arabic string literal (plain or f-string) in the sources, or
wrap them with L(ar, en) using a translation map.

    python tools/i18n_extract.py extract  -> tools/i18n_todo.json
    python tools/i18n_extract.py apply    <- tools/i18n_map.json
"""
import ast
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["sabbora/teacher.py", "sabbora/student.py"]
ARABIC = re.compile(r"[؀-ۿ]")


def _offsets(src):
    starts, pos = [0], 0
    for line in src.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts


def find(path):
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    line_starts = _offsets(src)
    lines = src.splitlines(keepends=True)

    class _Starts:  # ast columns are UTF-8 byte offsets -> convert to characters
        def __getitem__(self, i):
            return line_starts[i]

    def pos(lineno, col):
        line = lines[lineno - 1]
        return line_starts[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8"))

    starts = _Starts()
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        anc, inside = parents.get(node), False
        while anc is not None:
            if isinstance(anc, ast.JoinedStr):
                inside = True
                break
            anc = parents.get(anc)
        if inside:
            continue                      # piece of an f-string
        a, b = pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset)
        seg = src[a:b]
        if not ARABIC.search(seg):
            continue
        # skip docstrings and strings already wrapped in L(...)
        par = parents.get(node)
        if isinstance(par, ast.Expr):
            continue
        if isinstance(par, ast.Call) and getattr(par.func, "attr", getattr(par.func, "id", "")) == "L":
            continue
        out.append((a, b, seg))
    return src, out


def main():
    mode = sys.argv[1]
    if mode == "extract":
        todo = []
        for rel in FILES:
            _src, items = find(os.path.join(ROOT, rel))
            for _a, _b, seg in items:
                if seg not in todo:
                    todo.append(seg)
        with io.open(os.path.join(ROOT, "tools", "i18n_todo.json"), "w", encoding="utf-8") as f:
            json.dump(todo, f, ensure_ascii=False, indent=0)
        print(len(todo), "strings")
    elif mode == "apply":
        todo = json.load(io.open(os.path.join(ROOT, "tools", "i18n_todo.json"), encoding="utf-8"))
        en_lines = [l for l in io.open(os.path.join(ROOT, "tools", "i18n_en.txt"), encoding="utf-8").read().splitlines() if l.strip()]
        assert len(en_lines) == len(todo), (len(en_lines), len(todo))
        for snippet in en_lines:
            ast.parse(snippet, mode="eval")
        mapping = dict(zip(todo, en_lines))
        missing = 0
        for rel in FILES:
            path = os.path.join(ROOT, rel)
            src, items = find(path)
            prefix = "L" if rel.endswith("common.py") else "C.L"
            for a, b, seg in sorted(items, reverse=True):
                en = mapping.get(seg)
                if en is None:
                    missing += 1
                    print("MISSING", rel, seg[:70])
                    continue
                src = src[:a] + f"{prefix}({seg}, {en})" + src[b:]
            ast.parse(src)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(src)
        print("missing", missing)


if __name__ == "__main__":
    main()
