"""Revisar archivos candidatos a Git sin imprimir valores sensibles."""

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"account.json", "session.json", "club-account.json", "club-pending.json", "remote-pending.json", "checkout-details.json", "cart.json"}
PATTERNS = {
    "clave privada": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "token GitHub": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "JWT literal": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "credencial en URL": re.compile(r"https?://[^\s/]+:[^\s/]+@"),
    "email personal": re.compile(r"[\w.+-]+@(?:gmail\.com|hotmail\.com|outlook\.com|icloud\.com)\b", re.I),
    "ruta personal": re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
}


def main():
    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT)
    paths = sorted(set(path for path in files.decode().split("\0") if path))
    failures = []
    for name in paths:
        path = Path(name)
        if path.name in PRIVATE_NAMES or path.name.startswith((".env", "coupon-read-")) or path.suffix.lower() in {".har", ".pem", ".key", ".p12", ".pfx", ".mobileconfig", ".cer"}:
            failures.append((name, "archivo privado"))
            continue
        if any(part in {".venv", ".state", "__pycache__"} for part in path.parts):
            failures.append((name, "directorio privado o generado"))
            continue
        data = (ROOT / path).read_bytes()
        if b"\0" in data or path.suffix.lower() == ".png":
            continue  # Las imágenes se revisan visualmente antes de publicarlas.
        content = data.decode("utf-8")
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                failures.append((name, label))
    for name, label in failures:
        print(f"{name}: revisar {label}", file=sys.stderr)
    if failures:
        return 1
    print(f"{len(paths)} archivos candidatos revisados; no se detectaron valores sensibles con las reglas de publicación.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
