"""Instalar el wheel fuera del repo y validar las entradas sin red de Ametller."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
import zipfile


def main():
    wheel = Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(wheel) as archive:
        paths = archive.namelist()
        if any(name.startswith(("tests/", "docs/", "scripts/")) or name.endswith((".har", "account.json", "session.json", ".mobileconfig", ".cer", ".pem", ".key")) for name in paths):
            raise RuntimeError("El wheel contiene archivos ajenos al paquete o estado privado.")
    with tempfile.TemporaryDirectory(prefix="ametller-install-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / "bin" / "python"
        cli = root / "venv" / "bin" / "ametller"
        mcp = root / "venv" / "bin" / "ametller-mcp"
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=root, check=True, stdout=subprocess.DEVNULL)
        result = subprocess.run([str(cli), "capabilities", "--json"], cwd=root, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        assert data["payments_blocked"] and data["orders_blocked"]
        assert data["manual_checkout_browser_supported"] and not data["manual_checkout_mcp_supported"]
        assert "--review-only" in subprocess.check_output([str(cli), "checkout", "open", "--help"], cwd=root, text=True)
        assert data["personal_coupons_supported"] and data["personal_coupon_activation_supported"]
        assert data["mobile_club_login_supported"] and not data["mobile_club_automatic_refresh_supported"]
        assert "--status" in subprocess.check_output([str(cli), "coupons", "--help"], cwd=root, text=True)
        disconnected = subprocess.run([str(cli), "coupons", "--json", "--state-dir", str(root/"state")],
                                      cwd=root, capture_output=True, text=True)
        assert disconnected.returncode == 1 and not disconnected.stdout
        assert "import-capture" in json.loads(disconnected.stderr)["error"]
        version = subprocess.check_output([str(cli), "--version"], cwd=root, text=True).strip()
        installed = subprocess.check_output([str(python), "-c", "from importlib.metadata import version; print(version('ametller-cli'))"], cwd=root, text=True).strip()
        assert version == installed == data["version"]
        assert subprocess.check_output([str(mcp), "--version"], cwd=root, text=True).strip() == version
        missing = subprocess.run([str(mcp)], cwd=root, capture_output=True, text=True)
        assert missing.returncode == 1 and not missing.stdout and "extra MCP" in missing.stderr
        assert not (root / "account.json").exists()
    print(f"Wheel {wheel.name}: instalación limpia, metadatos y entradas CLI/MCP OK; ninguna llamada a Ametller.")


if __name__ == "__main__":
    main()
