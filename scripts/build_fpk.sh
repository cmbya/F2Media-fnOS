#!/usr/bin/env bash
set -euo pipefail

CURRENT_STAGE="bootstrap"
trap 'rc=$?; echo "[FPK][ERROR] stage=${CURRENT_STAGE} line=${LINENO} rc=${rc} command=${BASH_COMMAND}" >&2; exit "$rc"' ERR

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-0.5.3}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z" >&2; exit 2; }

FNPACK_BIN="${FNPACK_BIN:-${2:-}}"
[ -n "$FNPACK_BIN" ] || { echo "FNPACK_BIN is required" >&2; exit 2; }
[ -x "$FNPACK_BIN" ] || { echo "fnpack is not executable: $FNPACK_BIN" >&2; exit 2; }
FNPACK_BIN="$(cd "$(dirname "$FNPACK_BIN")" && pwd)/$(basename "$FNPACK_BIN")"

WORK="$ROOT/.build/fpk"
TEMPLATE_PARENT="$WORK/template"
PROJECT="$TEMPLATE_PARENT/f2media"
DIST="$ROOT/dist"
AUDIT="$ROOT/build-logs"
rm -rf "$WORK" "$DIST"
mkdir -p "$TEMPLATE_PARENT" "$DIST" "$AUDIT"

# Critical compatibility rule: create the staging tree with the current official
# fnpack template. Do not hand-invent wizard/ or other installer-facing layout.
CURRENT_STAGE="official fnpack create"
(
  cd "$TEMPLATE_PARENT"
  "$FNPACK_BIN" create f2media
)
[ -d "$PROJECT" ] || { echo "fnpack create did not produce $PROJECT" >&2; exit 1; }

CURRENT_STAGE="audit pristine fnpack template"
find "$PROJECT" -printf '%P\t%y\t%m\n' | sort > "$AUDIT/fnpack-template-tree.txt"
cp "$PROJECT/manifest" "$AUDIT/fnpack-template-manifest.txt" 2>/dev/null || true
cp "$PROJECT/config/privilege" "$AUDIT/fnpack-template-privilege.json" 2>/dev/null || true
cp "$PROJECT/config/resource" "$AUDIT/fnpack-template-resource.json" 2>/dev/null || true
if [ -d "$PROJECT/wizard" ]; then
  find "$PROJECT/wizard" -maxdepth 1 -type f -printf '%f\n' | sort > "$AUDIT/fnpack-template-wizard-files.txt"
  while IFS= read -r wf; do
    [ -n "$wf" ] || continue
    cp "$PROJECT/wizard/$wf" "$AUDIT/fnpack-template-wizard-$wf.json" 2>/dev/null || true
  done < "$AUDIT/fnpack-template-wizard-files.txt"
fi

CURRENT_STAGE="assemble app into official template"
# Remove sample app payload only. Keep fnpack-created root structure, LICENSE,
# wizard directory and any other template-owned installer metadata untouched.
rm -rf "$PROJECT/app"
mkdir -p "$PROJECT/app/bin" "$PROJECT/app/runtime" "$PROJECT/app/engines" "$PROJECT/app/ui/images"

cp -a "$ROOT/build/runtime/f2media-runtime" "$PROJECT/app/runtime/"
cp -a "$ROOT/build/engines/gallery-dl" "$PROJECT/app/engines/"
cp -a "$ROOT/build/php" "$PROJECT/app/php"
cp -a "$ROOT/build/short-videos" "$PROJECT/app/short-videos"
install -m755 "$ROOT/build/bin/yt-dlp" "$PROJECT/app/bin/yt-dlp"
install -m755 "$ROOT/build/bin/deno" "$PROJECT/app/bin/deno"
install -m755 "$ROOT/build/bin/ffmpeg" "$PROJECT/app/bin/ffmpeg"
install -m755 "$ROOT/build/bin/ffprobe" "$PROJECT/app/bin/ffprobe"
install -m755 "$ROOT/build/bin/x-cli" "$PROJECT/app/bin/x-cli"
install -m755 "$ROOT/build/bin/short_videos" "$PROJECT/app/bin/short_videos"
install -m755 "$ROOT/fnos/start-f2media" "$PROJECT/app/bin/start-f2media"
cp "$ROOT/LICENSE" "$PROJECT/app/LICENSE-F2MEDIA.txt"
cp "$ROOT/THIRD_PARTY.md" "$PROJECT/app/THIRD_PARTY.md"
mkdir -p "$PROJECT/app/third-party/x-cli"
for f in LICENSE NOTICE; do
  [ -f "$ROOT/build/vendor/x-cli/$f" ] && cp "$ROOT/build/vendor/x-cli/$f" "$PROJECT/app/third-party/x-cli/$f"
done
mkdir -p "$PROJECT/app/third-party/short-videos"
cp "$ROOT/f2media/parsers/short_videos_vendor/LICENSE" "$PROJECT/app/third-party/short-videos/LICENSE"
cp "$ROOT/f2media/parsers/short_videos_vendor/README.upstream.md" "$PROJECT/app/third-party/short-videos/README.upstream.md"
cp "$ROOT/f2media/parsers/short_videos_vendor/SOURCE_COMMIT.txt" "$PROJECT/app/third-party/short-videos/SOURCE_COMMIT.txt"
cp "$ROOT/fnos/app/ui/config" "$PROJECT/app/ui/config"
cp "$ROOT/fnos/ICON.PNG" "$PROJECT/app/ui/images/icon_64.png"
cp "$ROOT/fnos/ICON_256.PNG" "$PROJECT/app/ui/images/icon_256.png"

# Overwrite only files our app must own. wizard/ deliberately remains exactly
# as created by fnpack; F2Media does not declare empty wizard files.
cp "$ROOT/fnos/manifest" "$PROJECT/manifest"
rm -rf "$PROJECT/cmd" "$PROJECT/config"
mkdir -p "$PROJECT/cmd" "$PROJECT/config"
cp -a "$ROOT/fnos/cmd/." "$PROJECT/cmd/"
cp -a "$ROOT/fnos/config/." "$PROJECT/config/"
cp "$ROOT/fnos/ICON.PNG" "$PROJECT/ICON.PNG"
cp "$ROOT/fnos/ICON_256.PNG" "$PROJECT/ICON_256.PNG"
chmod 755 "$PROJECT"/cmd/*

# Keep root LICENSE from the official template. Store our license in app/ above.
python3 - "$PROJECT/manifest" "$VERSION" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
version = sys.argv[2]
lines = p.read_text(encoding="utf-8").splitlines()
out = []
seen = False
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key == "version":
        out.append(f"version={version}")
        seen = True
    elif key == "checksum":
        continue
    else:
        out.append(line)
if not seen:
    out.append(f"version={version}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

find "$PROJECT" -type f \( -name '.DS_Store' -o -name '._*' \) -delete
find "$PROJECT" -name '*.fpk' -delete

CURRENT_STAGE="compatibility-first contract preflight"
for f in "$PROJECT"/cmd/*; do bash -n "$f"; test -x "$f"; done
python3 - "$PROJECT" <<'PY'
import json
import sys
from pathlib import Path
from PIL import Image

root = Path(sys.argv[1])
required = [
    root / "manifest",
    root / "config" / "privilege",
    root / "config" / "resource",
    root / "ICON.PNG",
    root / "ICON_256.PNG",
    root / "app",
    root / "cmd",
    root / "wizard",
    root / "app" / "ui",
    root / "app" / "ui" / "config",
]
for path in required:
    if not path.exists():
        raise SystemExit(f"missing official fnpack path: {path}")

json.load(open(root / "config" / "privilege", encoding="utf-8"))
res = json.load(open(root / "config" / "resource", encoding="utf-8"))
ui = json.load(open(root / "app" / "ui" / "config", encoding="utf-8"))
allowed_resource_keys = {"data-share", "usr-local-linker", "docker-project"}
unknown = set(res) - allowed_resource_keys
if unknown:
    raise SystemExit(f"undocumented config/resource keys: {sorted(unknown)}")

entry = ui[".url"]["f2media.main"]
assert entry["icon"] == "images/icon_{0}.png"
assert str(entry["port"]) == "18082"
assert entry["url"] == "/"
assert entry["allUsers"] is True

manifest = {}
for raw in (root / "manifest").read_text(encoding="utf-8").splitlines():
    if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
        continue
    k, v = raw.split("=", 1)
    manifest[k.strip()] = v.strip().strip('"').strip("'")
for key in ("appname", "version", "display_name", "desc", "source", "platform", "maintainer"):
    if not manifest.get(key):
        raise SystemExit(f"manifest missing required/expected field: {key}")
assert manifest["appname"] == "f2media"
assert manifest["platform"] == "x86"
assert manifest["source"] == "thirdparty"
assert manifest["desktop_uidir"] == "ui"
assert manifest["desktop_applaunchname"] == "f2media.main"
assert manifest["service_port"] == "18082"
assert manifest["ctl_stop"] == "true"
# Compatibility-first: do not let system port precheck become an install/start gate.
assert manifest["checkport"] == "false"
if "checksum" in manifest:
    raise SystemExit("source manifest must not contain checksum; fnpack must generate it")

# Do not create our own empty wizard files. Any files present here must come
# from the official fnpack template itself.
for wf in sorted((root / "wizard").glob("*")):
    if wf.is_file():
        obj = json.load(open(wf, encoding="utf-8"))
        if not isinstance(obj, list):
            raise SystemExit(f"official template wizard file is not an array: {wf}")

for path, expected in [
    (root / "ICON.PNG", (64, 64)),
    (root / "ICON_256.PNG", (256, 256)),
    (root / "app" / "ui" / "images" / "icon_64.png", (64, 64)),
    (root / "app" / "ui" / "images" / "icon_256.png", (256, 256)),
]:
    with Image.open(path) as im:
        if im.size != expected:
            raise SystemExit(f"wrong icon size: {path}={im.size}, expected={expected}")
print("compatibility-first fnOS project preflight OK")
PY

CURRENT_STAGE="audit final fnpack project"
find "$PROJECT" -printf '%P\t%y\t%m\n' | sort > "$AUDIT/fnpack-final-tree.txt"
cp "$PROJECT/manifest" "$AUDIT/fnpack-final-manifest.txt"
cp "$PROJECT/config/privilege" "$AUDIT/fnpack-final-privilege.json"
cp "$PROJECT/config/resource" "$AUDIT/fnpack-final-resource.json"
cp "$PROJECT/app/ui/config" "$AUDIT/fnpack-final-ui.json"
find "$PROJECT/wizard" -maxdepth 1 -type f -printf '%f\n' | sort > "$AUDIT/fnpack-final-wizard-files.txt"

CURRENT_STAGE="record build provenance"
{
  echo "F2Media=$VERSION"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "fnpack_sha256=$(sha256sum "$FNPACK_BIN" | awk '{print $1}')"
  echo "build_uname=$(uname -a)"
  echo "build_libc=$(ldd --version 2>&1 | sed -n '1p' || true)"
  "$PROJECT/app/bin/ffmpeg" -version 2>&1 | sed -n '1p'
  "$PROJECT/app/bin/ffprobe" -version 2>&1 | sed -n '1p'
  "$PROJECT/app/bin/yt-dlp" --version
  "$PROJECT/app/bin/deno" --version 2>&1 | sed -n '1p'
  "$PROJECT/app/engines/gallery-dl/gallery-dl" --version || true
  "$PROJECT/app/bin/x-cli" version 2>/dev/null || "$PROJECT/app/bin/x-cli" --version 2>/dev/null || true
  "$PROJECT/app/bin/short_videos" --health 2>&1 | sed -n '1p'
} > "$PROJECT/app/BUILD-MANIFEST.txt" 2>&1

CURRENT_STAGE="official fnpack build"
(
  cd "$DIST"
  "$FNPACK_BIN" build --directory "$PROJECT"
)

mapfile -t GENERATED_FPKS < <(find "$DIST" -maxdepth 1 -type f -name '*.fpk' -print | sort)
if [ "${#GENERATED_FPKS[@]}" -ne 1 ]; then
  echo "official fnpack should produce exactly one .fpk, got ${#GENERATED_FPKS[@]}" >&2
  printf '  %s\n' "${GENERATED_FPKS[@]:-}" >&2
  exit 1
fi
RAW_FPK="${GENERATED_FPKS[0]}"
OUT="$DIST/F2Media_${VERSION}_fnOS_x86.fpk"
if [ "$RAW_FPK" != "$OUT" ]; then mv "$RAW_FPK" "$OUT"; fi

CURRENT_STAGE="reverse verify official fnpack output"
VERIFY="$WORK/verify"
mkdir -p "$VERIFY"
tar -xf "$OUT" -C "$VERIFY"
for path in manifest app.tgz config/privilege config/resource ICON.PNG ICON_256.PNG; do
  [ -e "$VERIFY/$path" ] || { echo "missing official FPK member: $path" >&2; exit 1; }
done
for path in cmd/main cmd/install_init cmd/install_callback cmd/upgrade_init cmd/upgrade_callback cmd/uninstall_init cmd/uninstall_callback cmd/config_init cmd/config_callback; do
  [ -e "$VERIFY/$path" ] || { echo "missing lifecycle member: $path" >&2; exit 1; }
done

python3 - "$VERIFY/manifest" "$VERIFY/app.tgz" "$VERSION" <<'PY'
from pathlib import Path
import hashlib, sys
manifest_path, app_tgz, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
values = {}
for raw in manifest_path.read_text(encoding="utf-8").splitlines():
    if "=" not in raw: continue
    k, v = raw.split("=", 1)
    values[k.strip()] = v.strip().strip('"').strip("'")
assert values.get("appname") == "f2media", values
assert values.get("platform") == "x86", values
assert values.get("version") == version, values
assert values.get("checkport") == "false", values
expected = values.get("checksum", "")
if not expected: raise SystemExit("official fnpack output manifest has no checksum")
actual = hashlib.md5(app_tgz.read_bytes()).hexdigest()
if expected != actual:
    raise SystemExit(f"official fnpack checksum mismatch: expected={expected} actual={actual}")
print("official manifest/checksum OK")
PY

OUTER_TREE="$WORK/outer-tree.txt"
tar -tf "$OUT" > "$OUTER_TREE"
cp "$OUTER_TREE" "$AUDIT/fpk-tree.txt"
cp "$VERIFY/manifest" "$AUDIT/fpk-manifest.txt"

INNER="$WORK/inner"
mkdir -p "$INNER"
tar -xf "$VERIFY/app.tgz" -C "$INNER"
for f in \
  "$INNER/bin/start-f2media" "$INNER/bin/ffmpeg" "$INNER/bin/ffprobe" "$INNER/bin/yt-dlp" "$INNER/bin/deno" "$INNER/bin/x-cli" \
  "$INNER/runtime/f2media-runtime/f2media-runtime" "$INNER/engines/gallery-dl/gallery-dl" \
  "$INNER/bin/short_videos" "$INNER/php/bin/php"; do
  test -x "$f" || { echo "missing executable in app.tgz: $f" >&2; exit 1; }
done
python3 - "$INNER/ui/config" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
entry = obj[".url"]["f2media.main"]
assert entry["icon"] == "images/icon_{0}.png"
assert str(entry["port"]) == "18082"
assert entry["allUsers"] is True
print("packaged UI config OK")
PY

test -f "$INNER/ui/images/icon_64.png"
test -f "$INNER/ui/images/icon_256.png"
test -f "$INNER/short-videos/adapter.php"
test -f "$INNER/short-videos/BilibiliParser.php"
"$INNER/bin/short_videos" --health | grep -q '"ok":true'

CURRENT_STAGE="final sha256"
sha256sum "$OUT" | tee "$DIST/SHA256SUMS.txt"
CURRENT_STAGE="done"
trap - ERR
echo "Official fnpack compatibility-first FPK self-check OK: $OUT"
