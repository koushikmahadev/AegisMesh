"""
Render documentation from templates with exact provenance from docs/MEASURED.json.

Templates in templates/ are rendered to:
- templates/DEMO_SCRIPT.template.md -> docs/DEMO_SCRIPT.md
- templates/LIMITATIONS.template.md -> docs/LIMITATIONS.md
- templates/README.template.md      -> README.md
- templates/index.template.html     -> web/index.html
"""
import os
import sys
import re
import json

sys.stdout.reconfigure(encoding="utf-8")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_measured():
    p = os.path.join(REPO_ROOT, "docs", "MEASURED.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def resolve_template(text: str, measured: dict) -> str:
    def replace_tag(match):
        raw_expr = match.group(1).strip()
        expr = raw_expr
        fmt = None
        filter_type = None

        if "|" in expr:
            expr, filter_type = expr.split("|", 1)
            expr = expr.strip()
            filter_type = filter_type.strip()

        if ":" in expr:
            expr, fmt = expr.split(":", 1)
            expr = expr.strip()
            fmt = fmt.strip()

        parts = expr.split(".")
        if parts[0] == "measured":
            parts = parts[1:]

        val = measured
        for p in parts:
            if isinstance(val, dict):
                if p not in val:
                    raise KeyError(f"Key '{p}' not found in measured dictionary (path: {raw_expr})")
                val = val[p]
            elif isinstance(val, list):
                idx = int(p)
                if idx < 0 or idx >= len(val):
                    raise IndexError(f"Index {idx} out of range in measured list (path: {raw_expr})")
                val = val[idx]
            else:
                raise TypeError(f"Cannot traverse into non-container {type(val)} with key '{p}' (path: {raw_expr})")

        if filter_type == "int":
            val = int(val)

        if fmt:
            return f"{val:{fmt}}"
        return str(val)

    return re.sub(r"\{\{([^}]+)\}\}", replace_tag, text)

def main():
    measured = load_measured()
    templates = [
        ("templates/DEMO_SCRIPT.template.md", "docs/DEMO_SCRIPT.md"),
        ("templates/LIMITATIONS.template.md", "docs/LIMITATIONS.md"),
        ("templates/README.template.md", "README.md"),
        ("templates/index.template.html", "web/index.html"),
    ]

    print("Rendering documentation from templates with MEASURED.json provenance...")
    for tmpl_rel, out_rel in templates:
        tmpl_path = os.path.join(REPO_ROOT, tmpl_rel)
        out_path = os.path.join(REPO_ROOT, out_rel)

        with open(tmpl_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        rendered = resolve_template(template_content, measured)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered)

        print(f"  ✓ {tmpl_rel} -> {out_rel}")

    print("All documents rendered successfully!")

if __name__ == "__main__":
    main()
