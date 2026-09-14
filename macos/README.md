# 小怪破甲 · Mac 独立版

**版本：1.3.4-mac.1｜配置引擎：1.3.4｜Apple Silicon / Intel**

单独的 macOS 下载包，不包含 Windows CMD 或 EXE。复用 Windows v1.3.4 的本地配置、引用修复、备份和恢复逻辑，不修改 Codex 程序或系统 Python。

## 快速开始

1. 将 Mac 版 ZIP **完整解压**到一个文件夹。
2. 双击 **启动小怪破甲.command**。
3. 安装完成后会请求打开 Codex；在新任务中输入 `你好` 或 `小怪` 检查指令载入。

默认优先使用本机 Python 3.11+。没有合适的 Python 时，启动器会按处理器架构下载固定版本的独立 Python，验证 SHA256 后存入本工具专用缓存。首次准备需要网络，之后可复用缓存；不运行 Homebrew，不使用 sudo，不替换系统解释器。

请使用 Mac 版完整 ZIP；单独下载 .command 文件不能运行。压缩包已写入 Unix 可执行权限和 LF 换行。也可在终端使用绝对路径启动：

```bash
/bin/bash "/你的解压路径/小怪破甲-Mac版/启动小怪破甲.command"
```

## 三个入口

| 文件 | 操作 |
| --- | --- |
| `启动小怪破甲.command` | 安装或更新本地指令配置 |
| `卸载小怪破甲.command` | 恢复本轮安装前的引用 |
| `查看小怪状态.command` | 只读取本地安装状态 |

交互窗口完成后按回车结束；`--json` 或 `XIAOGUAI_NO_PAUSE=1` 不暂停。

## 配置和恢复

配置目录依次选择：`--codex-home` → `CODEX_HOME` → `~/.codex`。

管理目录为 `managed-prompts/xiaoguai-oneclick/`。外部原指令文件不改，生成副本统一小怪身份。旧记录与当前有效引用不一致时，先保存旧记录、旧指令和配置快照，再按当前引用重建。

卸载只恢复本轮安装前的指令引用，保留之后新增的其他配置。发生引用修复时，恢复到修复前的当前引用；历史快照及修复前旧指令不删除。Mac 与 Windows 在各自用户目录运行，不互相替换安装包。

运行时缓存位于：

```text
~/Library/Caches/xiaoguai-oneclick/python-3.12.14-20260901-<架构>/
```

卸载指令配置不会删除用户安装的 Python，也不会删除独立运行时缓存。

## 参数与自动化

```bash
# 安装，不自动打开 Codex，以 JSON 输出结果
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --install --no-open --json

# 查看状态
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --status --json

# 恢复
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --restore --json

# 只操作独立测试目录
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --install --codex-home "/你的测试目录/codex-home" --no-open --json
```

显式指定配置目录后，查询和恢复需使用同一目录。设置 `--codex-home` 不会让正常打开的 Codex 自动改用该目录。

`--install`、`--restore`、`--status` 互斥；三个 .command 已各自带有操作参数，追加其他参数即可。

可通过 `XIAOGUAI_PYTHON="/Python的绝对路径/python3"` 指定已有解释器。该路径无效时直接报错，不偷偷改用其他解释器。`--help` 不会仅为显示帮助下载依赖。引导失败时错误写入 stderr，退出码为 2；正常进入 Python 后，`--json` 返回单个 JSON 对象。

## 小怪身份与确认口令

在新任务中仅输入 `hi`、`hello`、`你好`、`您好` 或 `在吗`，预期回复：

```text
「你好」
小怪在。👋
```

仅输入 `小怪`，预期回复：

```text
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789    QQ群1019953986
```

第二行频道与 QQ 群之间是 4 个 ASCII 空格；带有任务正文时不触发短回复。口令检查的是指令载入，不是模型能力测试。

## 验证范围

本版在 Windows 上完成共享引擎回归、Python 平台模拟与真实 Bash 下的隔离脚本测试；下载的两种官方 Python 运行时仅校验字节、压缩包布局及 Mach-O 架构，不在 Windows 上执行。

**尚未做 Mac 实机验证。** Finder 双击行为、原生运行时加载和真实 Codex 打开仍需 Mac 验证；不会把模拟测试写成 Mac 实测。具体结果见包内“验证记录.txt”。

独立运行时最低系统版本：Apple Silicon 为 macOS 11；Intel 为 macOS 10.15。Codex 自身的系统要求与本工具分别判断。运行时来源及固定校验值见 `macos/RUNTIME.md`。

## 交流

- TG 频道：https://t.me/XGYYDS789
- QQ 群：1019953986
