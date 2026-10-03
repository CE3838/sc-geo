#!/usr/bin/env bash
# Download a zipped geodatabase and list its layers, fields and a few rows.
# Usage: scripts/inspect_gdb.sh URL
set -euo pipefail
url="$1"; dir=$(mktemp -d)
curl -sSL --retry 3 -o "$dir/data.zip" "$url"
unzip -q "$dir/data.zip" -d "$dir"
gdb=$(find "$dir" -maxdepth 3 -name '*.gdb' -type d | head -1)
echo "== $gdb"
ogrinfo -ro -q "$gdb"
for layer in $(ogrinfo -ro -q "$gdb" | sed -nE 's/^[0-9]+: ([^ ]+).*/\1/p'); do
  echo "== layer $layer"
  ogrinfo -ro -so "$gdb" "$layer" | sed -n '/Feature Count/,$p' | head -40
  case "$layer" in
    DescriptionOfMapUnits|DataSources|Glossary|*Units*|*Sources*) ogrinfo -ro "$gdb" "$layer" | grep -vE '^\s*$' | head -150 ;;
  esac
done
