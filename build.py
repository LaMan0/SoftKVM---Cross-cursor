"""Construit SoftKVM avec PyInstaller.

- Windows : dist/SoftKVM.exe (fichier unique, sans console)
- macOS   : dist/SoftKVM.app (à construire SUR un Mac : PyInstaller ne fait pas
            de compilation croisée)

Usage :  python build.py
"""

import shutil
import subprocess
import sys

HIDDEN_IMPORTS = {
    "win32": [
        "pynput._util.win32",
        "pynput._util.win32_vks",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ],
    "darwin": [
        "pynput._util.darwin",
        "pynput._util.darwin_vks",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
    ],
}


def main():
    platform = sys.platform
    if platform not in HIDDEN_IMPORTS:
        sys.exit(f"Plateforme non prise en charge : {platform}")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "SoftKVM",
    ]
    for module in HIDDEN_IMPORTS[platform]:
        command += ["--hidden-import", module]
    command.append("run_softkvm.py")

    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)

    if platform == "win32":
        print("Exécutable créé : dist\\SoftKVM.exe")
    else:
        # --windowed sur macOS produit dist/SoftKVM.app.
        print("Application créée : dist/SoftKVM.app")
        shutil.rmtree("build", ignore_errors=True)


if __name__ == "__main__":
    main()
