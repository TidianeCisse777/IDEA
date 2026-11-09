#!/bin/bash
# Double-clic dans le Finder : installe le warehouse NeoLab sur ce Mac (voir LISEZMOI.md).
# Si macOS refuse de l'ouvrir : clic droit (ou Ctrl-clic) → Ouvrir → Ouvrir.
cd "$(dirname "$0")" && bash installer.sh "$@"
echo
read -r -p "Appuyer sur Entrée pour fermer cette fenêtre. " _ || true
