#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-0.1.7}"
FNPACK_BIN="${FNPACK_BIN:-${2:-}}"
[ -x "$FNPACK_BIN" ] || { echo "FNPACK_BIN is required" >&2; exit 2; }
WORK="$ROOT/.build/install-probe"
DIST="$ROOT/probe-dist"
rm -rf "$WORK" "$DIST"
mkdir -p "$WORK" "$DIST"
(
  cd "$WORK"
  "$FNPACK_BIN" create f2mediaprobe --without-ui true
)
P="$WORK/f2mediaprobe"
cat > "$P/manifest" <<MAN
appname=f2mediaprobe
version=$VERSION
display_name=F2Media Install Probe
desc=用于验证当前 fnOS 是否接受官方 fnpack 模板生成的最小第三方应用包
source=thirdparty
platform=all
maintainer=cmbya
ctl_stop=false
checkport=false
MAN
printf '%s\n' '{"defaults":{"run-as":"package"},"username":"f2mediaprobe","groupname":"f2mediaprobe"}' > "$P/config/privilege"
printf '%s\n' '{}' > "$P/config/resource"
# Keep official wizard/template structure untouched.
find "$P" -printf '%P\t%y\t%m\n' | sort > "$ROOT/build-logs/install-probe-project-tree.txt"
cp "$P/manifest" "$ROOT/build-logs/install-probe-manifest.txt"
(
  cd "$DIST"
  "$FNPACK_BIN" build --directory "$P"
)
mapfile -t fpks < <(find "$DIST" -maxdepth 1 -type f -name '*.fpk' -print)
[ "${#fpks[@]}" -eq 1 ] || { echo "probe fnpack output count=${#fpks[@]}" >&2; exit 1; }
out="$DIST/F2Media_Install_Probe_${VERSION}.fpk"
[ "${fpks[0]}" = "$out" ] || mv "${fpks[0]}" "$out"
tar -tf "$out" > "$ROOT/build-logs/install-probe-fpk-tree.txt"
sha256sum "$out" > "$DIST/SHA256SUMS.txt"
echo "install probe OK: $out"
