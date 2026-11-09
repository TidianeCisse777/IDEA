#!/usr/bin/env bash
# Fabrique la copie partagée du warehouse en deux zips de moins de 400 Mo (limite d'envoi constatée) :
#
#     bash scripts/build_shared_copy.sh data/warehouse_backups/neolab_warehouse_20261108_232541.dump
#
# Zip 1 : LISEZMOI, installer.sh, code (fichiers suivis par Git, sans data/), empreinte, morceau 0 de la base.
# Zip 2 : morceau 1 de la base. Les deux se décompressent dans le même dossier neolab_warehouse_<date>.
# Le nom de dossier et de fichiers dans le LISEZMOI doit correspondre à la date du dump.
set -euo pipefail
dump=$1
[ -f "$dump" ] && [ -f "$dump.sha256" ] || { echo "dump ou empreinte introuvable : $dump" >&2; exit 1; }
root=$(git rev-parse --show-toplevel)
base=$(basename "$dump" .dump)                 # neolab_warehouse_20261108_232541
tag=${base%_*}                                 # neolab_warehouse_20261108
grep -q "$base" "$root/docs/WAREHOUSE_PARTAGE_LISEZMOI.md" || { echo "le LISEZMOI ne cite pas $base" >&2; exit 1; }
out=$(cd "$(dirname "$dump")" && pwd)
work=$(mktemp -d); dir="$work/$tag"; mkdir -p "$dir"
split -b 380m -d -a 1 "$dump" "$dir/$base.dump.part"
[ "$(ls "$dir" | wc -l)" -eq 2 ] || { echo "la base ne tient pas en deux morceaux de 380 Mo" >&2; exit 1; }
cp "$dump.sha256" "$dir/"
cp "$root/docs/WAREHOUSE_PARTAGE_LISEZMOI.md" "$dir/LISEZMOI.md"
cp "$root/scripts/install_shared_copy.sh" "$dir/installer.sh"
(cd "$root" && git ls-files -co --exclude-standard | grep -v '^data/' | tar czf "$dir/IDEA-code.tar.gz" --transform 's,^,IDEA/,' -T -)
rm -f "$out/${tag}_1sur2.zip" "$out/${tag}_2sur2.zip"
(cd "$work" && zip -q -0 "$out/${tag}_1sur2.zip" "$tag/" "$tag/LISEZMOI.md" "$tag/installer.sh" "$tag/IDEA-code.tar.gz" \
     "$tag/$base.dump.sha256" "$tag/$base.dump.part0"
 zip -q -0 "$out/${tag}_2sur2.zip" "$tag/" "$tag/$base.dump.part1")
rm -rf "$work"
for z in "$out/${tag}_1sur2.zip" "$out/${tag}_2sur2.zip"; do
    size=$(wc -c < "$z")
    [ "$size" -lt $((400 * 1024 * 1024)) ] || { echo "$z dépasse 400 Mo" >&2; exit 1; }
    echo "$z : $((size / 1024 / 1024)) Mo"
done
