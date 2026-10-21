#!/bin/bash
# SoftKVM - lanceur macOS. Double-cliquez sur ce fichier pour ouvrir SoftKVM.
# La première fois, il installe les dépendances dans ~/.softkvm-venv.
cd "$(dirname "$0")" || exit 1

pause_and_exit() {
  echo
  read -r -p "Appuyez sur Entrée pour fermer cette fenêtre..." _
  exit "$1"
}

# Choisit le premier Python 3.9+ disponible (3.12 ou 3.13 conseillés).
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9 ou plus récent est introuvable."
  echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
  pause_and_exit 1
fi

VENV="$HOME/.softkvm-venv"
if ! "$VENV/bin/python" -c "import pynput, tkinter" >/dev/null 2>&1; then
  echo "Installation des dépendances (une seule fois, cela peut prendre une minute)..."
  rm -rf "$VENV"
  if ! "$PY" -m venv "$VENV" ||
     ! "$VENV/bin/python" -m pip install --upgrade pip >/dev/null ||
     ! "$VENV/bin/python" -m pip install -r requirements.txt; then
    echo "L'installation a échoué. Vérifiez votre connexion et relancez ce fichier."
    pause_and_exit 1
  fi
fi

echo "Démarrage de SoftKVM..."
echo "Au premier lancement, macOS demande deux autorisations (Réglages Système > Confidentialité et sécurité) :"
echo "  - Surveillance de l'entrée"
echo "  - Accessibilité"
echo "Accordez-les à Terminal (ou à Python), puis relancez SoftKVM."
echo

"$VENV/bin/python" run_softkvm.py
status=$?
if [ "$status" -ne 0 ]; then
  echo "SoftKVM s'est arrêté avec une erreur (code $status)."
  echo "Détails dans ~/softkvm.log"
  pause_and_exit "$status"
fi
