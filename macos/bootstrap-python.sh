#!/bin/bash
# macOS Bash 3.2. stdout is ONLY a verified interpreter path on success.
set -u
umask 077

fail() { printf '%s\n' "$1" >&2; exit 2; }
log() { printf '%s\n' "$1" >&2; }

script_path=${BASH_SOURCE[0]}
script_dir=${script_path%/*}
if [ "$script_dir" = "$script_path" ]; then script_dir=.; fi
script_dir=$(CDPATH= cd -- "$script_dir" && pwd -P) || exit 2
[ -f "$script_dir/runtime-pins.sh" ] || fail '缺少运行时清单，请完整解压 Mac 版安装包。'
[ -f "$script_dir/publish-runtime.py" ] || fail '缺少运行时提交组件，请完整解压 Mac 版安装包。'
. "$script_dir/runtime-pins.sh"

platform=$(uname -s 2>/dev/null) || fail '无法识别系统；未准备运行环境。'
[ "$platform" = Darwin ] || fail '此运行环境只适用于 macOS。'
machine=$(uname -m 2>/dev/null) || fail '无法识别 Mac 处理器。'
hardware_arm64=$(sysctl -in hw.optional.arm64 2>/dev/null) || hardware_arm64=0
if [ "$hardware_arm64" = 1 ]; then machine=arm64; fi
case "$machine" in
    arm64|aarch64) arch=arm64; runtime_url=$XG_ARM64_URL; archive_sha=$XG_ARM64_SHA256 ;;
    x86_64) arch=x86_64; runtime_url=$XG_X86_64_URL; archive_sha=$XG_X86_64_SHA256 ;;
    *) fail "不支持此处理器架构：$machine" ;;
esac

os_version=$(sw_vers -productVersion 2>/dev/null) || fail '无法读取 macOS 版本。'
os_major=${os_version%%.*}
os_rest=${os_version#*.}
os_minor=${os_rest%%.*}
case "$os_major:$os_minor" in *[!0-9:]*|:*|*:) fail "无法识别 macOS 版本：$os_version" ;; esac
if [ "$arch" = arm64 ]; then
    [ "$os_major" -ge 11 ] || fail 'Apple Silicon 运行环境需要 macOS 11 或更新版本。'
else
    if [ "$os_major" -lt 10 ] || { [ "$os_major" -eq 10 ] && [ "$os_minor" -lt 15 ]; }; then
        fail 'Intel 运行环境需要 macOS 10.15 或更新版本。'
    fi
fi

case "${HOME:-}" in /*) ;; *) fail 'HOME 不是有效的绝对路径。' ;; esac
home_dir=$(CDPATH= cd -- "$HOME" && pwd -P) || fail '无法访问用户主目录。'
[ "$home_dir" != / ] || fail '不能将根目录用作运行时主目录。'
cache_base=$home_dir/Library/Caches/xiaoguai-oneclick
for directory in "$home_dir/Library" "$home_dir/Library/Caches" "$cache_base"; do
    [ ! -L "$directory" ] || fail "缓存目录不能是符号链接：$directory"
    if [ -e "$directory" ] && [ ! -d "$directory" ]; then fail "缓存路径不是目录：$directory"; fi
    mkdir -p "$directory" || fail "无法创建缓存目录：$directory"
    [ ! -L "$directory" ] || fail "缓存目录在创建期间变化：$directory"
done
cache_real=$(CDPATH= cd -- "$cache_base" && pwd -P) || fail '无法访问运行时缓存。'
[ "$cache_real" = "$cache_base" ] || fail '缓存目录解析到其他位置，未写入。'
chmod 700 "$cache_real" || fail '无法设置本工具缓存权限。'

runtime_id=python-$XG_PYTHON_VERSION-$XG_PYTHON_BUILD-$arch
target=$cache_real/$runtime_id
python_path=$target/python/bin/$XG_PYTHON_BINARY
receipt=$target/.xiaoguai-runtime
lock=$cache_real/.$runtime_id.lock
lock_owned=0
lock_token=$$.$RANDOM
staging=

cleanup() {
    local status=$? resolved owner
    trap - EXIT HUP INT TERM
    if [ -n "$staging" ] && [ -d "$staging" ] && [ ! -L "$staging" ]; then
        resolved=$(CDPATH= cd -- "$staging" 2>/dev/null && pwd -P) || resolved=
        case "$resolved" in
            "$cache_real"/.prepare-"$runtime_id".*)
                if [ "$resolved" = "$staging" ] && [ "${resolved%/*}" = "$cache_real" ]; then
                    rm -rf -- "$staging" || log "保留未清理的临时目录：$staging"
                fi ;;
        esac
    fi
    if [ "$lock_owned" -eq 1 ] && [ -d "$lock" ] && [ ! -L "$lock" ] && [ ! -L "$lock/owner" ]; then
        owner=$(cat "$lock/owner" 2>/dev/null) || owner=
        if [ "$owner" = "$lock_token" ]; then
            rm -f -- "$lock/owner"
            rmdir "$lock" 2>/dev/null || :
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

check_cache() {
    local actual expected executable_sha
    [ -d "$target" ] && [ ! -L "$target" ] || return 1
    [ -f "$receipt" ] && [ ! -L "$receipt" ] || return 1
    [ -d "$target/python" ] && [ ! -L "$target/python" ] || return 1
    [ -d "$target/python/bin" ] && [ ! -L "$target/python/bin" ] || return 1
    [ -f "$python_path" ] && [ -x "$python_path" ] && [ ! -L "$python_path" ] || return 1
    executable_sha=$(shasum -a 256 "$python_path" 2>/dev/null) || return 1
    executable_sha=${executable_sha%% *}
    expected=$(printf '%s\n%s\n%s\n' "$runtime_id" "$archive_sha" "$executable_sha")
    actual=$(cat "$receipt" 2>/dev/null) || return 1
    [ "$actual" = "$expected" ] || return 1
    "$python_path" -I -c 'import sys, hashlib, json, pathlib, tempfile, tomllib, ssl; assert sys.version_info >= (3, 11)' >/dev/null 2>&1
}

[ ! -L "$target" ] || fail "运行时目标不能是符号链接：$target"
[ ! -L "$lock" ] || fail "运行时锁不能是符号链接：$lock"
attempt=0
until mkdir "$lock" 2>/dev/null; do
    [ -d "$lock" ] && [ ! -L "$lock" ] || fail "运行时锁不是普通目录：$lock"
    attempt=$((attempt + 1))
    [ "$attempt" -lt 30 ] || fail "其他运行时准备操作尚未结束，已保留现场：$lock"
    sleep 1
done
lock_owned=1
printf '%s\n' "$lock_token" > "$lock/owner" || fail '无法登记运行时准备锁。'

if [ -e "$target" ] || [ -L "$target" ]; then
    check_cache || fail "现有运行时缓存未通过检查，已保留：$target"
    printf '%s\n' "$python_path"
    exit 0
fi

staging=$(mktemp -d "$cache_real/.prepare-$runtime_id.XXXXXX") || fail '无法创建运行时临时目录。'
[ -d "$staging" ] && [ ! -L "$staging" ] || fail '临时运行时目录无效。'
case "$staging" in "$cache_real"/.prepare-"$runtime_id".*) ;; *) fail '临时运行时目录超出缓存范围。' ;; esac
[ "${staging%/*}" = "$cache_real" ] || fail '临时运行时目录层级不符。'
archive=$staging/runtime.tar.gz.part
log "首次准备 Python $XG_PYTHON_VERSION（$arch），下载后先校验，再使用。"
curl --fail --location --silent --show-error --retry 2 --retry-delay 1 \
    --connect-timeout 15 --max-time 600 --proto '=https' --proto-redir '=https' \
    --output "$archive" "$runtime_url" >&2 || fail '运行环境下载失败；未修改 Codex 配置，重新启动可重试。'
download_sha=$(shasum -a 256 "$archive") || fail '无法校验下载的运行环境。'
download_sha=${download_sha%% *}
[ "$download_sha" = "$archive_sha" ] || fail '运行环境 SHA256 不匹配；未解压、未执行下载内容。'

# These exact pinned archives are also reviewed during packaging: all entries
# and links stay under python/. The digest pins that reviewed byte sequence.
tar -tzf "$archive" > "$staging/members.txt" || fail '运行环境压缩包无法读取。'
while IFS= read -r member || [ -n "$member" ]; do
    case "$member" in python|python/*) ;; *) fail '压缩包成员不在 python 目录内。' ;; esac
    case "/$member/" in */../*) fail '压缩包成员包含上级目录。' ;; esac
done < "$staging/members.txt"
mkdir "$staging/tree" || fail '无法创建解压目录。'
tar -xzf "$archive" -C "$staging/tree" >&2 || fail '运行环境解压失败。'
candidate=$staging/tree/python/bin/$XG_PYTHON_BINARY
[ -f "$candidate" ] && [ -x "$candidate" ] && [ ! -L "$candidate" ] || fail '运行环境缺少可执行的 Python。'
"$candidate" -I -c 'import sys, hashlib, json, pathlib, tempfile, tomllib, ssl; assert sys.version_info >= (3, 11)' \
    >/dev/null 2>&1 || fail '下载的 Python 无法在本机运行；未修改 Codex 配置。'
executable_sha=$(shasum -a 256 "$candidate") || fail '无法登记 Python 校验值。'
executable_sha=${executable_sha%% *}
printf '%s\n%s\n%s\n' "$runtime_id" "$archive_sha" "$executable_sha" > "$staging/tree/.xiaoguai-runtime" \
    || fail '无法保存运行时校验记录。'
[ ! -e "$target" ] && [ ! -L "$target" ] || fail '运行时目标被其他操作创建，未覆盖。'
"$candidate" -I "$script_dir/publish-runtime.py" "$staging/tree" "$target" >&2 \
    || fail '无法原子保存运行环境；已有目标保持不变。'
check_cache || fail "运行时保存后未通过检查，已保留：$target"
log '独立 Python 运行环境已准备完成；不会替换系统 Python。'
printf '%s\n' "$python_path"
