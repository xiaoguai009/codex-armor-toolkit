<div align="center">

# 小怪 · Codex 全破甲

**Codex 全破甲｜面向 GPT-6 Astra 的指令配置工具，适用于渗透测试、逆向分析与开发工作流。**

**Windows v1.4.0 · Mac 独立版 v1.4.0-mac.1**

一键配置 · ACE 待资料 · 暴露检查 · 小怪身份 · 内置恢复

**[下载 Windows v1.4.0](downloads/xiaoguai-oneclick-v1.4.0.zip) · [下载 Mac v1.4.0-mac.1](downloads/xiaoguai-oneclick-v1.4.0-mac.1.zip)**

[Windows 快速开始](#windows-quick-start) · [Mac 快速开始](#mac-quick-start) · [ACE 与提示词隐私](docs/ACE-AND-PRIVACY.md) · [命令行参数](#options) · [状态与验证](#verify) · [恢复配置](#undo) · [交流与支持](#contact)

</div>

---

## Download / 按系统选择

| 系统 | 独立下载包 | 完整解压后运行 | 运行环境 |
| --- | --- | --- | --- |
| **Windows** | [v1.4.0 · Windows ZIP](downloads/xiaoguai-oneclick-v1.4.0.zip) | `启动小怪破甲.cmd` | EXE 内置运行时，无需另装 Python |
| **Mac · Apple Silicon / Intel** | [v1.4.0-mac.1 · Mac ZIP](downloads/xiaoguai-oneclick-v1.4.0-mac.1.zip) | `启动小怪破甲.command` | 优先已有 Python 3.11+；缺少时首次下载独立运行时 |

两个版本共用 v1.4.0 配置逻辑，**分别下载、分别解压**。Mac 包不含 Windows CMD / EXE，也不是 `.app`；不要只下载单个启动脚本。

**Mac 版尚未经过 Mac 实机验证。** 当前验证为 Windows 上的共享引擎回归、平台模拟与 Bash 脚本测试，详见 [Mac 使用说明](macos/README.md) 和 [Mac 验证记录](macos/验证记录.txt)。

## What / 这是什么

小怪破甲是一个 **Codex 本地指令配置工具**：通过 `config.toml` 顶层的 `model_instructions_file` 引用指令副本，保留外部原文件，在生成副本中统一“小怪”身份、普通问候与确认口令。

面向 **GPT-6 Astra** 使用场景，整理渗透测试、逆向分析与开发任务中的本地指令配置。工作流内容由已有指令与用户任务决定；本工具不内置扫描、利用或逆向分析引擎，也不自动执行这些工作流。

- **已有指令文件**：原文件不改；副本将旧身份名称统一为“小怪”，移除已知旧身份的精确唤醒段，保留其他正文，再追加身份与口令块。
- **没有原指令引用**：使用内置的简体中文开发基础指令，再追加口令块。
- **重复安装**：内容未变时不重复写入；旧版可直接再次安装，更新身份与口令块，保留其他正文及首次备份。
- **引用变化修复**：旧安装记录与当前有效引用不一致时，先保存历史快照，再按当前来源重建，不再直接报错退出。
- **需要恢复**：还原本轮安装前的指令引用；发生引用修复时，恢复到修复前的当前引用，保留其他设置与历史快照。
- **ACE 待资料模块**：提供资料模板与同一任务内后续消息续接规则，缺项不编造、不空跑；不包含可执行 ACE 绕过。
- **提示词隐私**：增加减少误回显的规则和只读脱敏暴露检查；不能阻止本机、API 接收方或解密代理提取提示词。

“Codex 全破甲”是项目名称，当前实现范围为本地指令配置、备份与恢复、ACE 资料模板和暴露提示检查。**本工具不支持绕过云端审核，不改变服务端模型能力或限制。** 安装器不修改 Codex 程序、模型权重、模型设置、推理档位、账号或 API 密钥，也不强制结束正在运行的 Codex。

当前测试覆盖本地配置流程，尚未进行 GPT-6 Astra 模型端兼容性测试。确认口令用于检查指令是否载入，不代表模型能力提升、限制绕过或“全破甲”效果已经验证。

## Highlights / 双平台版本特点

| 项目 | 当前实现 |
| --- | --- |
| 工作流定位 | 面向 GPT-6 Astra 的渗透测试、逆向分析与开发指令配置；不切换模型 |
| 启动方式 | Windows 双击 `.cmd`；Mac 双击 `.command`；分别提供恢复入口 |
| Windows 运行环境 | EXE 内置运行时，无需另装 Python 或下载运行依赖 |
| Mac 运行环境 | 优先 Python 3.11+；必要时首次下载固定版本、经 SHA256 校验的独立运行时，不替换系统 Python |
| 原文件保留 | 不覆盖外部原文件与首次备份；副本仅迁移旧身份名称、已知旧唤醒段及本工具管理块 |
| 小怪问候 | 新任务仅输入 `hi` / `你好` 等纯问候，预期显示“「你好」”与“小怪在。👋” |
| 两行确认 | 新任务输入“小怪”，预期回复诗句及包含频道、QQ 群的第二行 |
| ACE 资料准备 | 两个平台均提供 `--ace-template`；待资料、无后台监控、不执行绕过 |
| 减少误回显 | 不把文档、网页、日志的导出/外发指令当作授权；保留用户维护其自己文件的能力 |
| 暴露检查 | `--privacy-check` 只读配置与固定环境提示；不输出提示词、密钥或完整代理地址 |
| 发布白名单 | Windows / Mac 按明确列表打包，不递归收集本机配置、认证、历史备份与日志 |
| 旧版升级 | v1.3.x 可直接再次安装，更新管理块；诗句、频道与 QQ 群口令保持不变 |
| 备份与状态 | 使用独立的 `managed-prompts/xiaoguai-oneclick/` 目录 |
| 重复运行 | 内容一致时零写入，不覆盖首次备份 |
| 引用修复 | 按当前有效来源重建安装记录，旧状态、旧指令和首次备份保留到历史目录 |
| 路径一致性 | 相对引用按配置目录解析，同一目标不会误判为冲突 |
| 并发保护 | 校验配置与来源快照；保留外部修改及依赖文件，检测当前 profile 的独立引用 |
| 恢复方式 | 恢复本轮安装前引用；保留手动修改过的指令文件及修复历史 |
| Windows 回归 | 原 Windows / 共享引擎 89 项测试通过，覆盖引用修复、并发保护、身份迁移、源码、EXE 与 CMD 流程 |
| 完整验证范围 | Windows 上共 276 项回归：274 项通过、2 项跳过，新增功能及双平台打包检查已纳入；Mac 实机验收仍未完成，见 [Mac 验证记录](macos/验证记录.txt) |

<a id="quick-start"></a>

## Quick Start / 快速开始

<a id="windows-quick-start"></a>

### Windows · v1.4.0

#### 1. 下载并完整解压

下载 [小怪破甲 v1.4.0 安装包](downloads/xiaoguai-oneclick-v1.4.0.zip)，将压缩包完整解压到一个文件夹。

历史下载：[v1.3.4 Windows](downloads/xiaoguai-oneclick-v1.3.4.zip) · [v1.3.4-mac.1 Mac](downloads/xiaoguai-oneclick-v1.3.4-mac.1.zip) · [v1.3.2 安装包](downloads/xiaoguai-oneclick-v1.3.2.zip) · [v1.3.1 安装包](downloads/xiaoguai-oneclick-v1.3.1.zip)。

#### 2. 双击启动

双击 **`启动小怪破甲.cmd`**。

保持它与 **`小怪破甲安装器.exe`** 位于同一目录。安装器会定位配置目录、保存原配置备份、写入指令副本，并请求打开 Codex。

也可以在工具目录打开 PowerShell，直接运行：

```powershell
.\启动小怪破甲.cmd
```

需要命令行输出且不自动打开 Codex 时：

```powershell
.\小怪破甲安装器.exe --install --no-open --json
```

#### 旧版出现“当前引用被其他操作更改”

完整解压并运行 **v1.4.0** 的启动 CMD，不要只替换 CMD 而继续使用旧 EXE，也不需要先删除安装状态或备份。

新版以当前配置为准：读取有效的当前指令文件，保留原文件，在本地 `history/reference-<随机标识>/` 保存旧状态、旧指令、原首次备份及修复前配置，再生成新副本。当前已移除指令引用时，使用内置基础指令。

修复后卸载会恢复到**修复前的当前引用**，不会恢复成过期记录中的旧引用。指令文件缺失、空白、非 UTF-8、配置损坏或当前 profile 有独立引用时，仍保留现场并给出具体错误。

#### 3. 在新任务中验证

在 Codex **新任务**中输入 `你好` 验证“小怪在。👋”；输入 `小怪` 则验证诗句与群号。两种回复见下方 [Verify / 验证](#verify)。

#### Windows 源码入口

源码需要 **Python 3.11+**，运行只使用 Python 标准库。在仓库根目录执行：

```powershell
python .\oneclick.py --install
```

仅在独立测试目录写入配置的示例：

```powershell
python .\oneclick.py --install --codex-home ".\work\codex-test" --no-open --json
```

该命令只处理指定的测试目录，不会自动让正常启动的 Codex 改用这个目录。

<a id="mac-quick-start"></a>

### Mac · v1.4.0-mac.1

1. 下载 [Mac 独立安装包](downloads/xiaoguai-oneclick-v1.4.0-mac.1.zip)，**完整解压**。
2. 双击 **`启动小怪破甲.command`**；保持 `macos/` 文件夹和其余文件完整，不混用 Windows CMD / EXE。
3. 安装完成后会请求打开 Codex。在**新任务**输入 `你好` 或 `小怪`，检查指令载入。

启动器优先使用本机 Python 3.11+。没有合格解释器时，会按 Apple Silicon / Intel 架构下载固定版本的独立 Python，**先校验 SHA256，再使用**；首次准备需要网络，之后复用本工具缓存。不自动运行 Homebrew，不使用 `sudo`，不替换系统 Python。

终端安装示例（以 JSON 输出，不自动打开 Codex）：

```bash
/bin/bash "/你的解压路径/小怪破甲-Mac版/启动小怪破甲.command" --no-open --json
```

也可通过启动层调用，自动检查或准备运行环境：

```bash
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --install --no-open --json
```

**尚未做 Mac 实机验证**：Finder 双击、原生 Python 加载和真实 Codex 打开仍待实际验收。完整操作、运行时缓存与系统要求见 [Mac 使用说明](macos/README.md)，实际测试结果见 [Mac 验证记录](macos/验证记录.txt)。

#### Mac 源码入口

已有 **Python 3.11+** 时，在仓库根目录运行 Mac 专用入口：

```bash
python3 -I ./macos/run.py --install --no-open --json
```

仅操作独立测试目录：

```bash
python3 -I ./macos/run.py --install --codex-home "./work/codex-test" --no-open --json
```

与 Windows 一样，`--codex-home` 只选择本次工具操作的目录，不会让正常打开的 Codex 自动改用该目录。

<a id="options"></a>

## Options / 命令行参数

以下参数适用于 Windows 的 `oneclick.py` / `小怪破甲安装器.exe`，以及 Mac 的 `macos/run.py` / `macos/launch.sh`。

| 参数 | 作用 |
| --- | --- |
| `--install` | 安装指令配置；未指定操作时默认安装 |
| `--restore` | 恢复本次安装前的指令引用 |
| `--status` | 只读取本地安装状态，不调用模型 |
| `--ace-template` | 只显示 ACE 待资料模板；不安装、不执行绕过、不保存资料 |
| `--privacy-check` | 只读、脱敏检查配置与环境中的暴露提示；不检测真实流量 |
| `--codex-home "路径"` | 显式指定配置目录 |
| `--no-open` | 安装后不请求打开 Codex |
| `--json` | 以 JSON 输出实际结果 |
| `-h` / `--help` | 显示帮助 |

`--install`、`--restore`、`--status`、`--ace-template`、`--privacy-check` 五种操作互斥。各 `.cmd` / `.command` 已带对应操作参数，只需追加其他选项。

新增一键入口：**`准备ACE资料.cmd` / `准备ACE资料.command`** 和 **`检查提示词暴露.cmd` / `检查提示词暴露.command`**。Windows 新增 CMD 默认暂停便于阅读，自动化直接调用 EXE 或设置 `XIAOGUAI_NO_PAUSE=1`。

ACE 提供的是任务准备提示词，资料补齐不等于已经实现绕过；暴露检查未发现提示也不代表提示词不可提取。完整说明见 [ACE 与提示词隐私](docs/ACE-AND-PRIVACY.md)。

配置目录按以下顺序选择：

1. 命令行 `--codex-home`。
2. 环境变量 `CODEX_HOME`。
3. Windows 默认 `%USERPROFILE%\.codex`；Mac 默认 `~/.codex`。

Mac 可通过 `XIAOGUAI_PYTHON="/Python的绝对路径/python3"` 指定已有解释器；指定无效时直接报错。`--help` 不会仅为显示帮助下载运行时；`--json` 或 `XIAOGUAI_NO_PAUSE=1` 不会在结束时等待回车。

<a id="verify"></a>

## Verify / 验证

### 本地配置状态

#### Windows 状态

```powershell
.\小怪破甲安装器.exe --status --json
```

源码入口对应命令：

```powershell
python .\oneclick.py --status --json
```

#### Mac 状态

双击 **`查看小怪状态.command`**，或执行：

```bash
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --status --json
```

已安装 Python 3.11+ 时，在仓库根目录使用源码入口：

```bash
python3 -I ./macos/run.py --status --json
```

`--status` 检查本地安装记录与指令引用，不验证模型实际回复。安装命令的 JSON 结果中，`config_installed` 表示配置已写入，`model_reply_verified` 保持为 `false`。

`reference_repaired: true` 表示本次重建了过期引用记录；`recovery_path` 给出本地历史快照目录。重复安装内容未变时，`unchanged: true`，不再写入文件。

安装 JSON 另有 `support_modules`：ACE 为 `intake_only`、`bypass_implemented: false`；隐私规则为 `best_effort_response_guard`、`prevents_local_or_proxy_extraction: false`。这些值避免把提示词加载误当成功能突破。

### 小怪身份与普通问候

在新任务中仅输入 `hi`、`hello`、`你好`、`您好` 或 `在吗`，预期回复：

```text
「你好」
小怪在。👋
```

英文不区分大小写，忽略首尾空白及末尾普通问候标点。消息还包含任务正文时，不触发这条短回复规则，继续处理任务。仅输入 `小怪` 仍使用下方诗句口令，不改为普通问候。

名称迁移只作用于工具生成的副本；不会改写外部原文件或首次恢复备份。安装 JSON 中的 `assistant_name` 与 `expected_greeting` 只是预期配置值，不是模型端测试结果。

### 新任务确认口令

输入：

```text
小怪
```

预期只回复以下两行；中间仅一个换行，不添加空行、缩进或其他文字。第二行频道与 QQ 群之间恰好为 4 个 ASCII 空格：

```text
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789    QQ群1019953986
```

旧任务可能仍使用创建时的指令。优先新建任务；若仍未载入，退出并重新打开 Codex 后再验证。消息中除了“小怪”还有其他正文时，不触发这一确认口令。

### 源码测试

Windows：

```powershell
python -B -m unittest discover -s tests -v
```

Mac / Python 3.11+：

```bash
python3 -B -m unittest discover -s tests -v
```

测试使用独立临时配置目录。Windows 且根目录存在已构建 EXE 时会运行 EXE 与 CMD 测试；不满足条件时，这部分测试会跳过。完整跨平台回归使用仓库源码，各平台 ZIP 只包含适用的测试子集。当前验证见 [验证记录.txt](验证记录.txt) 和 [Mac 验证记录](macos/验证记录.txt)。上述 Mac 命令是运行方式，不代表已完成 Mac 实测。

<a id="undo"></a>

## Undo / 恢复安装前配置

### Windows 恢复

双击 **`卸载小怪破甲.cmd`**，或在工具目录执行：

```powershell
.\小怪破甲安装器.exe --restore --json
```

源码入口：

```powershell
python .\oneclick.py --restore --json
```

### Mac 恢复

双击 **`卸载小怪破甲.command`**，或执行：

```bash
/bin/bash "/你的解压路径/小怪破甲-Mac版/macos/launch.sh" --restore --json
```

已安装 Python 3.11+ 时，在仓库根目录使用源码入口：

```bash
python3 -I ./macos/run.py --restore --json
```

### 两个平台共同的恢复规则

如果安装时指定了 `--codex-home`，查询状态和恢复时也应使用同一目录。

恢复会还原本轮安装前的指令引用，而不是用旧备份覆盖整份当前配置。发生过引用修复时，以最近一次修复前的当前引用为恢复目标：

- 保留安装后新增的其他设置。
- 清理本轮未被修改的指令文件和安装记录；历史目录及修复前旧指令不删除。
- 手动修改过的指令文件保留，并在结果中列出。
- 没有待恢复记录时可重复运行。
- 当前指令引用被其他操作改动时停止覆盖，保留现有配置与备份。

如果安装前已使用其他自定义身份，恢复后仍会加载那份原文件；“恢复安装前引用”不等于恢复 Codex 默认身份。

Mac 恢复配置不会卸载用户已有 Python，也不会清理本工具的独立运行时缓存；缓存说明见 [Mac 使用说明](macos/README.md)。

## Layout / 项目结构

```text
.
├── README.md                         # GitHub 项目首页
├── README.txt                        # Windows 安装与升级说明
├── oneclick.py                       # v1.4.0 Windows 入口与共享配置实现
├── config_engine.py                  # 配置读写、备份与恢复逻辑
├── task_support.py                   # ACE 待资料与减少误回显提示词
├── privacy_check.py                  # 只读、脱敏的暴露提示检查
├── build_windows_package.py          # Windows 白名单打包与核对
├── 启动小怪破甲.cmd                  # Windows 一键安装入口
├── 卸载小怪破甲.cmd                  # Windows 一键恢复入口
├── 准备ACE资料.cmd                   # Windows 资料模板入口
├── 检查提示词暴露.cmd                # Windows 暴露检查入口
├── 小怪破甲安装器.exe                # Windows 独立可执行文件
├── 启动小怪破甲.command              # Mac 一键安装入口
├── 卸载小怪破甲.command              # Mac 一键恢复入口
├── 查看小怪状态.command              # Mac 状态查看入口
├── 准备ACE资料.command               # Mac 资料模板入口
├── 检查提示词暴露.command            # Mac 暴露检查入口
├── build-requirements.txt             # 固定版本的构建依赖
├── 验证记录.txt                      # Windows v1.4.0 构建与验证记录
├── 免责声明.txt                      # 原包附带文件
├── 直接点击启动小怪破甲.txt          # 原包附带提示文件
├── macos/
│   ├── README.md                     # Mac 使用说明
│   ├── run.py                        # Mac 安装 / 状态 / 恢复入口
│   ├── launch.sh                     # Python 发现与启动层
│   ├── bootstrap-python.sh           # 独立运行时下载、校验与缓存
│   ├── runtime-pins.sh               # 固定运行时版本与 SHA256
│   ├── publish-runtime.py            # 运行时原子发布 helper
│   ├── build_package.py              # Mac 独立 ZIP 打包与验证
│   ├── RUNTIME.md                    # 运行时来源、缓存与系统要求
│   └── 验证记录.txt                  # Mac 版实际验证范围与结果
├── tests/
│   ├── test_config_engine.py
│   ├── test_oneclick.py
│   ├── test_reference_repair.py       # 引用变化、历史快照与并发回归
│   ├── test_macos_entry.py
│   ├── test_macos_shell.py
│   ├── test_macos_bootstrap.py
│   ├── test_macos_package.py
│   ├── test_support_features.py
│   ├── test_privacy_check.py
│   └── test_windows_package.py
├── assets/
│   ├── support.jpg                   # 用户提供的赞赏码原图
│   └── qq-group.jpg                  # 用户提供的 QQ 群原图
├── downloads/
│   ├── xiaoguai-oneclick-v1.4.0.zip   # Windows 当前独立安装包
│   ├── xiaoguai-oneclick-v1.4.0-mac.1.zip # Mac 当前独立安装包
│   ├── xiaoguai-oneclick-v1.3.4.zip   # 历史 Windows 安装包
│   ├── xiaoguai-oneclick-v1.3.4-mac.1.zip # 历史 Mac 安装包
│   ├── xiaoguai-oneclick-v1.3.2.zip   # 历史版本安装包
│   └── xiaoguai-oneclick-v1.3.1.zip   # 历史版本安装包
├── docs/
│   ├── ACE-AND-PRIVACY.md             # 新模块使用方法与真实保护边界
│   └── UPLOAD.md                     # GitHub 上传说明
└── .gitignore
```

配置副本与状态位于所选 Codex 配置目录下：Windows 默认 `%USERPROFILE%\.codex`，Mac 默认 `~/.codex`；指定 `--codex-home` 时以指定目录为准：

```text
CODEX_HOME/
├── config.toml
└── managed-prompts/
    └── xiaoguai-oneclick/
        ├── active.md                      # 默认指令副本名；重名时使用新文件名
        ├── install-state.json             # 安装状态
        ├── config.toml.before-oneclick.bak # 原配置存在时保存的首次备份
        └── history/                       # 仅发生引用修复时创建
            └── reference-<随机标识>/
                ├── install-state.json
                ├── config-before-repair.toml
                ├── config-before-first-install.bak
                └── prompts/               # 旧指令快照
```

历史快照中的配置或首次备份文件仅在原文件存在时保存。该目录属于用户本地恢复数据，不包含在安装包或仓库中。

<a id="contact"></a>

## Contact / 交流与支持

- **TG 频道**：[频道 @XGYYDS789](https://t.me/XGYYDS789)
- **QQ 群**：Ai逆向技术交流群 · **1019953986**

点击下方图片可查看完整原图。

<table>
  <tr>
    <th align="center" width="50%">赞赏支持</th>
    <th align="center" width="50%">QQ 群交流</th>
  </tr>
  <tr>
    <td align="center" valign="top">
      <a href="assets/support.jpg"><img src="assets/support.jpg" alt="赞赏支持二维码原图" width="320"></a>
    </td>
    <td align="center" valign="top">
      <a href="assets/qq-group.jpg"><img src="assets/qq-group.jpg" alt="Ai逆向技术交流群，群号 1019953986" width="320"></a>
    </td>
  </tr>
</table>
