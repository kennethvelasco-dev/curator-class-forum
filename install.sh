#!/bin/bash
#
# Grok CLI installer — https://x.ai/cli/install.sh
#
# Auth: GROK_DEPLOYMENT_KEY (takes precedence) or ~/.grok/auth.json from `grok login`.
# Env: GROK_CHANNEL (stable|alpha|enterprise, default: stable), GROK_BIN_DIR, GROK_PROXY_URL
#
# Usage:
#   curl -fsSL https://x.ai/cli/install.sh | bash            # latest stable
#   curl -fsSL https://x.ai/cli/install.sh | bash -s 0.1.42  # specific version
#   GROK_DEPLOYMENT_KEY=<key> bash <(curl -fsSL https://x.ai/cli/install.sh)
#
# Windows: run under Git for Windows / MSYS2 Bash (same curl | bash flow); WSL
# uses the Linux binary.

set -e

TARGET="$1"

if [[ -n "$TARGET" ]] && [[ ! "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9._]+)?$ ]]; then
    echo "Invalid version format: $TARGET (expected X.Y.Z or X.Y.Z-suffix)" >&2
    exit 1
fi

DOWNLOADER=""
if command -v curl >/dev/null 2>&1; then
    DOWNLOADER="curl"
elif command -v wget >/dev/null 2>&1; then
    DOWNLOADER="wget"
else
    echo "Either curl or wget is required but neither is installed" >&2
    exit 1
fi

download_file() {
    local url="$1" output="$2"
    if [ "$DOWNLOADER" = "curl" ]; then
        if [ -n "$output" ]; then
            curl -fsSL -o "$output" "$url"
        else
            curl -fsSL "$url"
        fi
    else
        if [ -n "$output" ]; then
            wget -q -O "$output" "$url"
        else
            wget -q -O - "$url"
        fi
    fi
}

# Parallel byte-range download. Falls back to single-connection download_file
# whenever HEAD lacks Content-Length, the file is small (<16 MiB), curl is
# unavailable, or any chunk fetch / concat fails.
download_file_parallel() {
    local url="$1" output="$2"
    if [ "$DOWNLOADER" != "curl" ]; then
        download_file "$url" "$output"
        return
    fi
    local size
    size=$(curl -fsSL --head "$url" 2>/dev/null | awk -F'[: \r\n]+' 'tolower($1)=="content-length"{print $2; exit}')
    if [ -z "$size" ] || ! [ "$size" -ge 16777216 ] 2>/dev/null; then
        download_file "$url" "$output"
        return
    fi
    local n=8
    local chunk_size=$(( (size + n - 1) / n ))
    local tmpdir
    tmpdir=$(mktemp -d 2>/dev/null) || { download_file "$url" "$output"; return; }
    local pids=() i start end
    for i in $(seq 0 $((n - 1))); do
        start=$((i * chunk_size))
        end=$((start + chunk_size - 1))
        [ $end -ge $size ] && end=$((size - 1))
        curl -fsSL -r "${start}-${end}" -o "${tmpdir}/$(printf 'chunk.%03d' "$i")" "$url" &
        pids+=($!)
    done
    local all_ok=true pid
    for pid in "${pids[@]}"; do
        wait "$pid" || all_ok=false
    done
    if [ "$all_ok" = true ] && cat "${tmpdir}"/chunk.* > "$output" 2>/dev/null; then
        rm -rf "$tmpdir"
        return 0
    fi
    rm -rf "$tmpdir"
    download_file "$url" "$output"
}

# Return 0 if a HEAD request for the URL gets HTTP 404.
is_not_found() {
    local url="$1" code
    if [ "$DOWNLOADER" = "curl" ]; then
        code=$(curl -o /dev/null -sSL -w '%{http_code}' --head "$url" 2>/dev/null) || true
    else
        code=$(wget --server-response --spider "$url" 2>&1 | awk '/HTTP\//{print $2}' | tail -1) || true
    fi
    [ "$code" = "404" ]
}

fetch_compressed() {
    local url="$1" tmp="$2" out="$3"
    shift 3
    is_not_found "$url" && return 1
    download_file_parallel "$url" "$tmp" || return 1
    # pipefail catches a decoder error (corrupt) or the over-cap SIGPIPE so the
    # caller falls back; head bounds the write so a bomb cannot fill the disk.
    # A real binary is ~170 MiB, well under the cap.
    local max=$((512 * 1024 * 1024))
    if (set -o pipefail; "$@" <"$tmp" 2>/dev/null | head -c "$max" >"$out"); then
        [ -s "$out" ] && return 0
    fi
    rm -f "$out"
    return 1
}

fetch_binary() {
    local base="$1" out="$2" tmp
    tmp=$(mktemp 2>/dev/null) || tmp=""
    if [ -n "$tmp" ]; then
        if command -v zstd >/dev/null 2>&1 && fetch_compressed "${base}.zst" "$tmp" "$out" zstd -q -dc; then
            rm -f "$tmp"
            return 0
        fi
        if command -v gzip >/dev/null 2>&1 && fetch_compressed "${base}.gz" "$tmp" "$out" gzip -dc; then
            rm -f "$tmp"
            return 0
        fi
        rm -f "$tmp"
    fi
    download_file_parallel "$base" "$out"
}

# JSON field extractor — extract a top-level string value using sed.
json_get() {
    local json="$1" field="$2"
    # Extract value (handling \" inside strings), then unescape JSON sequences.
    printf '%s' "$json" | sed -n -E 's/.*"'"$field"'"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p' | head -1 \
        | sed -e 's/\\"/"/g' -e 's/\\n/\'$'\n''/g' -e 's/\\t/\'$'\t''/g' -e 's/\\\\/\\/g'
}

# Read a token from ~/.grok/auth.json for the given scope key.
# Format: {"scope_url": {"key": "token"}, ...}
read_grok_token() {
    local auth_file="$HOME/.grok/auth.json"
    local scope="$1"
    [ -f "$auth_file" ] || return 1
    # Flatten to one line then extract: find the scope, then the "key" value after it
    tr -d '\n' < "$auth_file" | sed -n 's|.*"'"$scope"'"[[:space:]]*:[[:space:]]*{[^}]*"key"[[:space:]]*:[[:space:]]*"\([^"]*\)".*|\1|p' | head -1
}

# Resolve auth: GROK_DEPLOYMENT_KEY > OIDC token > legacy token
OIDC_SCOPE="https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
LEGACY_SCOPE="https://accounts.x.ai/sign-in"
AUTH_SOURCE=""

if [ -n "$GROK_DEPLOYMENT_KEY" ]; then
    AUTH_SOURCE="deployment key"
    echo "Auth: using deployment key." >&2
else
    OIDC_TOKEN=$(read_grok_token "$OIDC_SCOPE" 2>/dev/null) || true
    LEGACY_TOKEN=$(read_grok_token "$LEGACY_SCOPE" 2>/dev/null) || true
    if [ -n "$OIDC_TOKEN" ]; then
        AUTH_SOURCE="auth.json (oidc)"
        echo "Auth: using OIDC token from ~/.grok/auth.json." >&2
    elif [ -n "$LEGACY_TOKEN" ]; then
        AUTH_SOURCE="auth.json (legacy)"
        echo "Auth: using legacy token from ~/.grok/auth.json." >&2
    fi
fi

case "$(uname -s)" in
    Darwin) os="macos" ;;
    Linux)  os="linux" ;;
    # Git for Windows / MSYS2 / Cygwin host — native Windows builds
    MINGW* | MSYS* | CYGWIN*) os="windows" ;;
    *)      echo "Unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
    x86_64|amd64|AMD64) arch="x86_64" ;;
    arm64|aarch64|ARM64) arch="aarch64" ;;
    *)                    echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

# Rosetta lies: in a translated shell on Apple Silicon, uname -m reports
# x86_64. Install the native arm64 build (faster startup, no translation).
# sysctl lives in /usr/sbin, which pruned PATHs often drop — resolve the
# binary first (PATH, then absolute) so the probe cannot quietly keep
# x86_64. A probe that runs and finds no key is a genuine Intel Mac.
if [ "$os" = "macos" ] && [ "$arch" = "x86_64" ]; then
    sysctl_bin="$(command -v sysctl || echo /usr/sbin/sysctl)"
    if [ "$("$sysctl_bin" -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
        echo "Apple Silicon detected (Rosetta shell); installing the native arm64 build." >&2
        arch="aarch64"
    fi
fi

BASE_URL_PRIMARY="https://x.ai/cli"
BASE_URL_FALLBACK="https://storage.googleapis.com/grok-build-public-artifacts/cli"
DOWNLOAD_DIR="$HOME/.grok/downloads"
BIN_DIR="${GROK_BIN_DIR:-$HOME/.grok/bin}"
mkdir -p "$DOWNLOAD_DIR" "$BIN_DIR"

# The Cursor CLI's getConfigDir(): CURSOR_CONFIG_DIR, else $XDG_CONFIG_HOME/cursor, else ~/.cursor.
cursor_config_dir() {
    local explicit="${CURSOR_CONFIG_DIR:-}" xdg="${XDG_CONFIG_HOME:-}"
    if [ -n "${explicit//[[:space:]]/}" ]; then
        printf '%s' "$explicit"
    elif [ -n "${xdg//[[:space:]]/}" ]; then
        printf '%s/cursor' "$xdg"
    else
        printf '%s/.cursor' "$HOME"
    fi
}
# The Cursor CLI's switch record in the file $1, read as every Grok reader reads it: `JSON.parse`,
# then a switch only for an object whose schema is the number 1, written `1`, and whose state is
# "pending" or "active". Prints active, pending, other (JSON that records no switch) or invalid, and
# nothing when it can't read the file (no od or awk, or either fails). The cases all readers agree
# on are crates/codegen/xai-grok-config/testdata/cursor-switch-records.tsv.
cursor_switch_verdict() {
    command -v od >/dev/null && command -v awk >/dev/null || return 0
    # awk reads the bytes as od prints them, 16 numbers to a line: no awk then meets a long line,
    # where some take time in proportion to the position for each character, or a NUL
    { LC_ALL=C od -A n -v -t u1 "$1" || echo failed; } | LC_ALL=C awk '
        BEGIN {
            for (b = 32; b < 127; b++) chr[b] = sprintf("%c", b)
            for (b = 48; b < 58; b++) hex[b] = b - 48
            for (b = 97; b < 103; b++) hex[b] = b - 87
            for (b = 65; b < 71; b++) hex[b] = b - 55
            accepts["zero"] = accepts["int"] = accepts["frac"] = accepts["exp"] = 1
            expect = "value"; depth = 0; bad = 0; top = ""; tok = ""
            schema = ""; state = "\001"; key = ""
        }
        function closed() { expect = depth ? "comma" : "end" }
        # A value of kind at the top of the record, under key.
        function member(kind, text) {
            if (depth != 1 || stack[1] != "{") return
            if (key == "schema") schema = kind == "number" ? text : ""
            if (key == "state") state = kind == "string" ? text : "\001"
        }
        # The first 8 characters of a string or number: enough to tell the keys, states and schema
        # the record names, so a long one costs nothing.
        function keep(c) { if (length(text) < 8) text = text c }
        # The byte b inside a string, decoded far enough to compare with ASCII.
        function in_string(b) {
            if (escape == 1) {
                escape = 0
                if (b == 34 || b == 92 || b == 47) keep(chr[b])
                else if (b == 98 || b == 102 || b == 110 || b == 114 || b == 116) keep("\001")
                else if (b == 117) { escape = 2; code = 0 }
                else bad = 1
            } else if (escape) {
                if (!(b in hex)) { bad = 1; return }
                code = code * 16 + hex[b]
                if (++escape == 6) { escape = 0; keep(code >= 32 && code < 127 ? chr[code] : "\001") }
            } else if (b == 34) {
                tok = ""
                if (is_key) { if (depth == 1) key = text; expect = "colon" }
                else { member("string", text); closed() }
            } else if (b == 92) escape = 1
            else if (b < 32) bad = 1
            else keep(b < 127 ? chr[b] : "\001")
        }
        # Whether the byte b goes on the number being read; a number that cannot end there is bad.
        function in_number(b,    digit) {
            digit = b >= 48 && b <= 57
            if (number == "start" && b == 45) number = "minus"
            else if ((number == "start" || number == "minus") && b == 48) number = "zero"
            else if ((number == "start" || number == "minus") && digit) number = "int"
            else if (number == "int" && digit) number = "int"
            else if ((number == "zero" || number == "int") && b == 46) number = "dot"
            else if ((number == "dot" || number == "frac") && digit) number = "frac"
            else if ((number == "zero" || number == "int" || number == "frac") && (b == 101 || b == 69)) number = "e"
            else if (number == "e" && (b == 43 || b == 45)) number = "sign"
            else if ((number == "e" || number == "sign" || number == "exp") && digit) number = "exp"
            else {
                if (!(number in accepts)) bad = 1
                tok = ""; member("number", text); closed()
                return 0
            }
            keep(chr[b])
            return 1
        }
        function byte(b) {
            if (tok == "string") { in_string(b); return }
            if (tok == "number" && in_number(b)) return
            if (tok == "literal") {
                if (b != word[at] + 0) { bad = 1; return }
                if (++at > letters) { tok = ""; member("literal", ""); closed() }
                return
            }
            if (bad || b == 32 || b == 9 || b == 10 || b == 13) return
            if (expect == "end") { bad = 1; return }
            if (expect == "colon") { if (b == 58) expect = "value"; else bad = 1; return }
            if (expect == "comma") {
                if (b == 44) expect = stack[depth] == "{" ? "key" : "value"
                else if ((b == 125 && stack[depth] == "{") || (b == 93 && stack[depth] == "[")) { depth--; closed() }
                else bad = 1
                return
            }
            if (expect == "key" || expect == "key_or_close") {
                if (b == 125 && expect == "key_or_close") { depth--; closed(); return }
                if (b != 34) { bad = 1; return }
                tok = "string"; is_key = 1; escape = 0; text = ""
                return
            }
            # expect is value or value_or_close
            if (b == 93 && expect == "value_or_close") { depth--; closed(); return }
            if (depth == 0) top = b
            if (b == 123 || b == 91) {
                member("container", "")
                stack[++depth] = b == 123 ? "{" : "["
                expect = b == 123 ? "key_or_close" : "value_or_close"
            } else if (b == 34) {
                tok = "string"; is_key = 0; escape = 0; text = ""
            } else if (b == 45 || (b >= 48 && b <= 57)) {
                tok = "number"; number = "start"; text = ""; in_number(b)
            } else if (b == 116 || b == 102 || b == 110) {
                # true, false or null, as bytes
                letters = split(b == 116 ? "116 114 117 101" : b == 102 ? "102 97 108 115 101" : "110 117 108 108", word, " ")
                tok = "literal"; at = 2
            } else bad = 1
        }
        $1 == "failed" { failed = 1 }
        { for (f = 1; f <= NF && !bad; f++) byte($f + 0) }
        END {
            if (failed) exit
            if (tok == "number" && !bad) byte(32)
            if (bad || tok != "" || expect != "end") print "invalid"
            else if (top == 123 && schema == "1" && (state == "active" || state == "pending")) print state
            else print "other"
        }
    '
}
# Whether the Cursor CLI's switch record holds grok and agent, in $BIN_DIR and on PATH: only a
# record that reads as a pending or active switch does. Anything else there holds nothing and gets a
# note saying why, so a stale or foreign file never keeps grok and agent from an install.
cursor_owns_names() {
    local dir path up why="" needs=""
    dir=$(cursor_config_dir)
    path="$dir/grok-switch.json"
    if [ -e "$dir" ] && [ ! -d "$dir" ]; then
        why="$dir is not a directory"
    elif [ ! -e "$path" ]; then
        # No record, unless a directory on the way to it can't be searched
        up=$dir
        until [ -e "$up" ] || [ "$up" = "$(dirname "$up")" ]; do up=$(dirname "$up"); done
        if [ -d "$up" ] && [ ! -x "$up" ]; then why="can't read $path"; fi
    elif [ -d "$path" ] || [ ! -r "$path" ]; then
        why="can't read $path"
    else
        case "$(cursor_switch_verdict "$path")" in
            active | pending) return 0 ;;
            invalid) why="$path is not JSON" ;;
            other) why="$path records no switch (schema 1, state pending or active)" ;;
            *)
                # A record that can't be read could be a switch: never take grok and agent over it
                command -v od >/dev/null || needs="od"
                command -v awk >/dev/null || needs="${needs:+$needs and }awk"
                if [ -n "$needs" ]; then
                    echo "Error: can't read the Cursor CLI's switch record $path: reading it needs $needs. Install $needs and run this again, or delete $path if the Cursor CLI is no longer installed." >&2
                else
                    echo "Error: can't read the Cursor CLI's switch record $path. Run this again, or delete $path if the Cursor CLI is no longer installed." >&2
                fi
                exit 1
                ;;
        esac
    fi
    if [ -n "$why" ]; then echo "Note: ignoring the Cursor CLI's switch record: $why." >&2; fi
    return 1
}
cursor_names=""
if cursor_owns_names; then cursor_names=1; fi

platform="${os}-${arch}"
CHANNEL="${GROK_CHANNEL:-stable}"
case "$CHANNEL" in
    stable|alpha|enterprise) ;;
    *)
        echo "Invalid GROK_CHANNEL: '${CHANNEL}' (expected stable, alpha, or enterprise)" >&2
        exit 1
        ;;
esac

# Pick a working BASE_URL: try Cloudflare-fronted x.ai first, fall back to
# direct GCS if it's unreachable. The probe doubles as the channel-pointer
# fetch when no explicit TARGET was passed, so the happy path costs zero
# extra HTTP requests.
if [ -z "$TARGET" ]; then echo "Fetching latest ${CHANNEL} version..." >&2; fi
probe_result=$(download_file "${BASE_URL_PRIMARY}/${CHANNEL}" 2>/dev/null) || true
if [ -n "$probe_result" ]; then
    BASE_URL="$BASE_URL_PRIMARY"
else
    echo "Note: ${BASE_URL_PRIMARY} unreachable, falling back to direct GCS." >&2
    BASE_URL="$BASE_URL_FALLBACK"
    probe_result=$(download_file "${BASE_URL}/${CHANNEL}" 2>/dev/null) || true
fi

if [ -n "$TARGET" ]; then
    version="$TARGET"
else
    version=$(printf '%s' "$probe_result" | tr -d '\r' | head -n1 | tr -d '[:space:]')
    if [ -z "$version" ]; then
        echo "Error: failed to fetch latest version from ${BASE_URL_PRIMARY}/${CHANNEL} and ${BASE_URL_FALLBACK}/${CHANNEL}" >&2
        exit 1
    fi
fi

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9._]+)?$ ]]; then
    echo "Invalid version format: $version (expected X.Y.Z or X.Y.Z-suffix)" >&2
    exit 1
fi

if [ -n "$AUTH_SOURCE" ]; then
    echo "Installing Grok $version ($platform, $AUTH_SOURCE)..." >&2
else
    echo "Installing Grok $version ($platform)..." >&2
fi

binary_path="$DOWNLOAD_DIR/grok-$platform"
artifact_base="${BASE_URL}/grok-${version}-${platform}"

if [ "$os" = "windows" ]; then
    binary_path="${binary_path}.exe"
fi

binary_tmp="${binary_path}.tmp.$$"
rm -f "$binary_tmp" 2>/dev/null || true

echo "  Downloading grok ${version}..." >&2
if [ "$os" = "windows" ]; then
    if ! fetch_binary "${artifact_base}.exe" "$binary_tmp"; then
        if ! fetch_binary "$artifact_base" "$binary_tmp"; then
            rm -f "$binary_tmp"
            if is_not_found "${artifact_base}.exe"; then
                echo "Error: Grok is not yet available for your system ($platform)." >&2
            else
                echo "Error: binary download failed (${artifact_base}.exe and ${artifact_base})" >&2
            fi
            exit 1
        fi
    fi
elif ! fetch_binary "$artifact_base" "$binary_tmp"; then
    rm -f "$binary_tmp"
    if is_not_found "$artifact_base"; then
        echo "Error: Grok is not yet available for your system ($platform)." >&2
    else
        echo "Error: binary download failed from ${artifact_base}" >&2
    fi
    exit 1
fi

if [ "$os" = "windows" ]; then
    mv -f "$binary_tmp" "$binary_path"
    # Symlinks require Developer Mode on Windows; copy instead.
    # If the exe is locked by a running process, rename it aside then retry.
    if [ -n "$cursor_names" ]; then
        echo "  Left $BIN_DIR/grok.exe and $BIN_DIR/agent.exe to the Cursor CLI, which switched them." >&2
    else
        for bin_name in grok.exe agent.exe; do
            rm -f "$BIN_DIR/$bin_name.old" 2>/dev/null || true  # stale backup from prior update
            if ! cp -f "$binary_path" "$BIN_DIR/$bin_name" 2>/dev/null; then
                mv -f "$BIN_DIR/$bin_name" "$BIN_DIR/$bin_name.old" 2>/dev/null || true
                if ! cp -f "$binary_path" "$BIN_DIR/$bin_name" 2>/dev/null; then
                    # Rollback: restore the old binary so the install isn't broken.
                    mv -f "$BIN_DIR/$bin_name.old" "$BIN_DIR/$bin_name" 2>/dev/null || true
                    echo "Error: failed to install $bin_name" >&2
                    exit 1
                fi
            fi
        done
        echo "  Binary installed to $BIN_DIR/grok.exe and $BIN_DIR/agent.exe." >&2
    fi
else
    chmod +x "$binary_tmp"
    if ! "$binary_tmp" --version </dev/null >/dev/null 2>&1; then
        echo "Error: downloaded grok failed to run; keeping the existing install." >&2
        rm -f "$binary_tmp"
        exit 1
    fi
    mv -f "$binary_tmp" "$binary_path"
    # Use relative symlinks when BIN_DIR and DOWNLOAD_DIR share a parent
    # (default layout: ~/.grok/bin and ~/.grok/downloads are siblings).
    # Relative symlinks survive Docker bind-mounts with a different $HOME.
    if [ "$(dirname "$BIN_DIR")" = "$(dirname "$DOWNLOAD_DIR")" ]; then
        link_target="../$(basename "$DOWNLOAD_DIR")/$(basename "$binary_path")"
    else
        link_target="$binary_path"
    fi
    if [ -n "$cursor_names" ]; then
        echo "  Left $BIN_DIR/grok and $BIN_DIR/agent to the Cursor CLI, which switched them." >&2
    else
        ln -sf "$link_target" "$BIN_DIR/grok"
        ln -sf "$link_target" "$BIN_DIR/agent"
        echo "  Binary linked to $BIN_DIR/grok and $BIN_DIR/agent." >&2
    fi
fi

# Generate shell completions (best-effort)
mkdir -p "$HOME/.grok/completions/bash" "$HOME/.grok/completions/zsh"
"$binary_path" completions bash > "$HOME/.grok/completions/bash/grok.bash" 2>/dev/null || true
"$binary_path" completions zsh  > "$HOME/.grok/completions/zsh/_grok"     2>/dev/null || true
# Fish: write to the auto-loaded completions dir so it works immediately
if mkdir -p "$HOME/.config/fish/completions" 2>/dev/null; then
    "$binary_path" completions fish > "$HOME/.config/fish/completions/grok.fish" 2>/dev/null || true
fi

# Persist installer source and channel to config
CONFIG_FILE="$HOME/.grok/config.toml"
CLI_BLOCK="installer = \"internal\""
case "$CHANNEL" in
    alpha) CLI_BLOCK="${CLI_BLOCK}\nchannel = \"alpha\"" ;;
    enterprise) CLI_BLOCK="${CLI_BLOCK}\nchannel = \"enterprise\"" ;;
esac
if [ ! -f "$CONFIG_FILE" ]; then
    printf '[cli]\n%b\n' "$CLI_BLOCK" > "$CONFIG_FILE"
elif grep -q '^\[cli\]' "$CONFIG_FILE"; then
    tmp="$CONFIG_FILE.tmp.$$"
    awk -v block="$CLI_BLOCK" '
        /^\[cli\][[:space:]]*(#.*)?$/ { print; printf "%s\n", block; in_cli=1; next }
        /^\[.*\][[:space:]]*(#.*)?$/  { in_cli=0 }
        in_cli && /^[[:space:]]*(installer|channel)[[:space:]]*=/ { next }
        { print }
    ' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
else
    printf '\n[cli]\n%b\n' "$CLI_BLOCK" >> "$CONFIG_FILE"
fi

# Fetch managed_config.toml + requirements.toml from server (deployment key only).
if [ -n "$GROK_DEPLOYMENT_KEY" ]; then
    PROXY_URL="${GROK_PROXY_URL:-https://cli-chat-proxy.grok.com/v1}"
    # Refuse cleartext / userinfo / empty-host proxies before attaching the key.
    proxy_authority="${PROXY_URL#*://}"
    proxy_authority="${proxy_authority%%[/?#]*}"
    proxy_ok=
    case "$PROXY_URL" in
        [hH][tT][tT][pP][sS]://*)
            case "$proxy_authority" in
                ""|*@*) ;;
                *) proxy_ok=1 ;;
            esac
            ;;
    esac
    if [ -z "$proxy_ok" ]; then
        echo "Error: GROK_PROXY_URL must be an https:// URL." >&2
        exit 1
    fi
    echo "  Fetching deployment config..." >&2
    DEPLOY_RESPONSE=""
    AUTH_HEADER_FILE=$(mktemp 2>/dev/null) || AUTH_HEADER_FILE=""
    if [ -n "$AUTH_HEADER_FILE" ]; then
        chmod 600 "$AUTH_HEADER_FILE" 2>/dev/null || true
        printf 'Authorization: Bearer %s\n' "$GROK_DEPLOYMENT_KEY" > "$AUTH_HEADER_FILE"
        DEPLOY_RESPONSE=$(curl -sS -f --proto '=https' \
            -H "@${AUTH_HEADER_FILE}" \
            "${PROXY_URL}/deployment/config" 2>/dev/null) || DEPLOY_RESPONSE=""
        : > "$AUTH_HEADER_FILE" 2>/dev/null || true
        rm -f "$AUTH_HEADER_FILE"
    fi
    if [ -z "$DEPLOY_RESPONSE" ]; then
        echo "  Warning: failed to fetch deployment config from ${PROXY_URL}/deployment/config" >&2
    fi
    if [ -n "$DEPLOY_RESPONSE" ]; then
        MANAGED_CONFIG=$(json_get "$DEPLOY_RESPONSE" "managed_config")
        REQUIREMENTS=$(json_get "$DEPLOY_RESPONSE" "requirements")
        if [ -n "$MANAGED_CONFIG" ] && [ "$MANAGED_CONFIG" != "null" ]; then
            printf '%s\n' "$MANAGED_CONFIG" > "$HOME/.grok/managed_config.toml"
            echo "  Managed config applied." >&2
        else
            rm -f "$HOME/.grok/managed_config.toml"
        fi
        if [ -n "$REQUIREMENTS" ] && [ "$REQUIREMENTS" != "null" ]; then
            printf '%s\n' "$REQUIREMENTS" > "$HOME/.grok/requirements.toml"
            echo "  Requirements applied." >&2
        else
            rm -f "$HOME/.grok/requirements.toml"
        fi
    fi
fi

if [ -n "$cursor_names" ]; then
    echo "Grok $version downloaded to $binary_path; switch back with 'cursor-agent update --channel cursor' to run it." >&2
elif [ "$os" = "windows" ]; then
    echo "Grok $version installed to $BIN_DIR/grok.exe" >&2
else
    echo "Grok $version installed to $BIN_DIR/grok" >&2
fi

# --- Ensure grok is on PATH ---

path_has_dir() {
    case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac
}

# Try to symlink into a directory already on PATH so grok works immediately
# without restarting the shell. Candidate dirs in preference order. Skipped while
# the Cursor CLI owns the names, so a link earlier on PATH cannot shadow its shims.
SYMLINK_CREATED=""
if [ "$os" != "windows" ] && [ -n "$cursor_names" ]; then
    echo "  Left grok and agent on PATH to the Cursor CLI, which switched them." >&2
elif [ "$os" != "windows" ] && ! path_has_dir "$BIN_DIR"; then
    for candidate in "$HOME/.local/bin" "/usr/local/bin"; do
        if path_has_dir "$candidate" && [ -d "$candidate" ] && [ -w "$candidate" ]; then
            ln -sf "$BIN_DIR/grok" "$candidate/grok"
            ln -sf "$BIN_DIR/agent" "$candidate/agent"
            SYMLINK_CREATED="$candidate"
            echo "  Symlinked $candidate/grok -> $BIN_DIR/grok" >&2
            echo "  Symlinked $candidate/agent -> $BIN_DIR/agent" >&2
            break
        fi
    done
fi

# Also update shell config so ~/.grok/bin is on PATH for future sessions
user_shell="$(basename "${SHELL:-}")"
config_file=""

case "$user_shell" in
    bash) config_file="$HOME/.bashrc" ;;
    zsh)  config_file="$HOME/.zshrc" ;;
    fish) config_file="$HOME/.config/fish/config.fish" ;;
esac

if [ -n "$config_file" ]; then
    mkdir -p "$(dirname "$config_file")"

    # Resolve symlinks so tmp+mv rewrites the stow/dotfiles target, not the link.
    if [ -e "$config_file" ] || [ -L "$config_file" ]; then
        _cf="$config_file"
        _depth=0
        while [ -L "$_cf" ] && [ "$_depth" -lt 40 ]; do
            _link="$(readlink "$_cf")" || break
            case "$_link" in
                /*) _cf="$_link" ;;
                *)  _cf="$(cd "$(dirname "$_cf")" && pwd -P)/$_link" ;;
            esac
            _depth=$((_depth + 1))
        done
        # Still a symlink (cycle/cap): leave original path so we never rewrite the link.
        if [ ! -L "$_cf" ]; then
            config_file="$(cd "$(dirname "$_cf")" && pwd -P)/$(basename "$_cf")"
        fi
        unset _cf _link _depth
    fi

    # Build the new installer block
    if [ "$user_shell" = "fish" ]; then
        new_block='# >>> grok installer >>>
fish_add_path $HOME/.grok/bin
# <<< grok installer <<<'
    elif [ "$user_shell" = "zsh" ]; then
        new_block='# >>> grok installer >>>
export PATH="$HOME/.grok/bin:$PATH"
fpath=(~/.grok/completions/zsh $fpath)
autoload -Uz compinit && compinit -C
# <<< grok installer <<<'
    else
        new_block='# >>> grok installer >>>
export PATH="$HOME/.grok/bin:$PATH"
[[ -r "$HOME/.grok/completions/bash/grok.bash" ]] && source "$HOME/.grok/completions/bash/grok.bash"
# <<< grok installer <<<'
    fi

    if grep -qs "grok installer" "$config_file" 2>/dev/null; then
        # Replace existing block in-place (strip old >>> to <<< lines, insert new)
        tmp="$config_file.tmp.$$"
        awk '
            /# >>> grok installer >>>/ { skip=1; next }
            /# <<< grok installer <<</ { skip=0; next }
            !skip { print }
        ' "$config_file" > "$tmp" && mv "$tmp" "$config_file"
    else
        [ -f "$config_file" ] && cp "$config_file" "$config_file.bak.$(date +%s)"

        # macOS bash: ensure bash_profile sources bashrc
        if [ "$user_shell" = "bash" ] && [ "$(uname -s)" = "Darwin" ]; then
            if [ -f "$HOME/.bash_profile" ] && ! grep -qs "source ~/.bashrc" "$HOME/.bash_profile"; then
                printf '\n[[ -r ~/.bashrc ]] && source ~/.bashrc\n' >> "$HOME/.bash_profile"
            fi
        fi
    fi

    printf '\n%s\n' "$new_block" >> "$config_file"
    echo "  Updated $BIN_DIR in PATH in $config_file." >&2
fi

echo "" >&2
# While switched, grok and agent run what the Cursor CLI switched them to, not this build.
if [ -n "$cursor_names" ]; then
    echo "Run 'cursor-agent update --channel cursor' to switch grok and agent back to this build, or delete $(cursor_config_dir)/grok-switch.json if the Cursor CLI is no longer installed." >&2
elif path_has_dir "$BIN_DIR" || [ -n "$SYMLINK_CREATED" ]; then
    echo "Run 'grok' or 'agent' to get started!" >&2
elif [ -n "$config_file" ]; then
    echo "Restart your terminal, then run 'grok' or 'agent' to get started!" >&2
else
    echo "Add $BIN_DIR to your PATH, then run 'grok' or 'agent' to get started:" >&2
    echo '  export PATH="$HOME/.grok/bin:$PATH"' >&2
fi

if [ "$os" = "windows" ]; then
    echo "To use grok from cmd.exe or PowerShell, add %USERPROFILE%\\.grok\\bin to your PATH." >&2
fi
