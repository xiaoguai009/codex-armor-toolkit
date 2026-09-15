#!/bin/bash
# Compatible with macOS /bin/bash 3.2. All arguments remain separate strings.
SCRIPT_PATH=${BASH_SOURCE[0]}
SCRIPT_DIR=${SCRIPT_PATH%/*}
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then SCRIPT_DIR=.; fi
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P) || exit 2

json_requested=0
help_requested=0
for argument in "$@"; do
    case "$argument" in
        --json) json_requested=1 ;;
        --help|-h) help_requested=1 ;;
    esac
done

finish() {
    local status=$1
    if [ "$json_requested" -eq 0 ] && [ "${XIAOGUAI_NO_PAUSE:-0}" != 1 ] \
        && [ -t 0 ] && [ -t 1 ]; then
        printf '\n按回车关闭此窗口…' >&2
        IFS= read -r reply || :
    fi
    exit "$status"
}

fail() {
    printf '%s\n' "$1" >&2
    finish "${2:-2}"
}

basic_help() {
    printf '%s\n' \
        '小怪破甲 macOS 版 1.4.0-mac.1' \
        '用法：/bin/bash macos/launch.sh [--install | --restore | --status | --ace-template | --privacy-check] [选项]' \
        '  --ace-template     显示 ACE 待资料模板，不安装或执行绕过' \
        '  --privacy-check    只读检查暴露提示，不输出提示词或完整地址' \
        '  --codex-home PATH  指定本次操作的 Codex 配置目录' \
        '  --no-open          安装后不打开 Codex' \
        '  --json             仅由 Python 入口输出 JSON，不暂停' \
        '  --help, -h         显示帮助；不为查看帮助下载运行环境' \
        '优先使用 Python 3.11+；可用 XIAOGUAI_PYTHON 指定解释器文件路径。' \
        '没有合适解释器时，由 bootstrap-python.sh 准备独立运行环境。' \
        'XIAOGUAI_NO_PAUSE=1 可关闭交互窗口的回车暂停。'
}

platform=$(uname -s 2>/dev/null) || fail '无法识别当前系统；请在 macOS 中运行此启动器。'
[ "$platform" = Darwin ] || fail '此启动器仅支持 macOS（Darwin）；Windows 请使用 CMD 版本。'
[ -f "$ROOT/macos/run.py" ] || fail '找不到 macos/run.py，请先完整解压 Mac 版安装包。'

python_path=
try_python() {
    local candidate=$1 candidate_dir candidate_name absolute_dir absolute_path
    [ -n "$candidate" ] && [ -f "$candidate" ] && [ -x "$candidate" ] || return 1
    candidate_dir=${candidate%/*}
    candidate_name=${candidate##*/}
    if [ "$candidate_dir" = "$candidate" ]; then candidate_dir=.; fi
    absolute_dir=$(CDPATH= cd -- "$candidate_dir" 2>/dev/null && pwd -P) || return 1
    absolute_path=$absolute_dir/$candidate_name
    "$absolute_path" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1 || return 1
    python_path=$absolute_path
    return 0
}

if [ "${XIAOGUAI_PYTHON+x}" = x ]; then
    try_python "$XIAOGUAI_PYTHON" \
        || fail 'XIAOGUAI_PYTHON 指定的文件不是可运行的 Python 3.11+；未使用其他解释器。'
else
    path_python=$(type -P python3 2>/dev/null) || path_python=
    if ! try_python "$path_python"; then
        for candidate in "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
            if try_python "$candidate"; then break; fi
        done
    fi
fi

if [ -z "$python_path" ]; then
    if [ "$help_requested" -eq 1 ]; then
        if [ "$json_requested" -eq 1 ]; then basic_help >&2; else basic_help; fi
        finish 0
    fi
    [ -f "$ROOT/macos/bootstrap-python.sh" ] \
        || fail '找不到 macos/bootstrap-python.sh，请先完整解压 Mac 版安装包。'
    if bootstrap_python=$(/bin/bash "$ROOT/macos/bootstrap-python.sh"); then
        case "$bootstrap_python" in
            /*) ;;
            *) fail '独立运行环境未返回 Python 的绝对文件路径。' ;;
        esac
        case "$bootstrap_python" in
            *$'\n'*|*$'\r'*) fail '独立运行环境返回了多行或无效的 Python 路径。' ;;
        esac
        try_python "$bootstrap_python" \
            || fail '独立运行环境的 Python 3.11+ 校验失败；未运行安装程序。'
    else
        bootstrap_status=$?
        fail '独立 Python 运行环境准备失败。' "$bootstrap_status"
    fi
fi

"$python_path" -I "$ROOT/macos/run.py" "$@"
python_status=$?
finish "$python_status"
