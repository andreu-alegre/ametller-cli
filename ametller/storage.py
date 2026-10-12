"""Estado privado local, bloqueo entre procesos y escritura atómica."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


class Error(Exception):
    pass


class Storage:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("AMETLLER_HOME", "~/.ametller")).expanduser()

    def prepare(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def read(self, name, default=None):
        try:
            with (self.root / name).open() as file:
                return json.load(file)
        except FileNotFoundError:
            return default
        except (ValueError, OSError):
            raise Error(f"Estado local inválido: {name}. Revisa {self.root}.") from None

    def write(self, name, value):
        if name in ("account.json", "session.json", "club-account.json", "checkout-details.json"):
            project = Path(__file__).resolve().parents[1]
            if self.root.resolve().is_relative_to(project):
                raise Error("Las sesiones deben guardarse fuera del repositorio. Usa ~/.ametller o un directorio privado externo.")
        self.prepare()
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(value, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.root / name)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def delete(self, name):
        (self.root / name).unlink(missing_ok=True)

    @contextmanager
    def lock(self, name="cart"):
        self.prepare()
        fd = os.open(self.root / (name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)
