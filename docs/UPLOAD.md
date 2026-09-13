# 小怪 · Codex 全破甲 / GitHub 上传说明

本目录是小怪破甲 **v1.3.4** 的待上传材料，保留 **v1.3.2 / v1.3.1** 历史安装包。首页参考 [codex-config-toolkit](https://github.com/dafage10086/codex-config-toolkit) 的文档结构，使用小怪破甲自己的功能、参数、版本和文件布局；没有复制参考项目的功能、模型版本或许可证声明。

上传并提交到目标仓库后，文件才会发布到 GitHub；仅整理本地材料不会创建仓库或提交。

## 本次发布目标

- **GitHub 所有者**：`xiaoguai009`
- **仓库名称**：`codex-armor-toolkit`
- **仓库地址**：[xiaoguai009/codex-armor-toolkit](https://github.com/xiaoguai009/codex-armor-toolkit)
- **可见性**：公开

目标为上述已有仓库；是否完成本次发布，以 GitHub 上的实际提交为准。上文的第三方仓库仅用于文档结构参考，不是上传目标。

## 仓库首页与 About 简介

- **项目显示名称**：小怪 · Codex 全破甲
- **版本**：v1.3.4
- **About / Description**：

```text
Codex 全破甲｜面向 GPT-6 Astra 的指令配置工具，适用于渗透测试、逆向分析与开发工作流。
```

在 GitHub 仓库首页右侧 **About** 的编辑入口，将上面这一行填入 **Description** 并保存。这个字段用于仓库卡片和列表中的简介，不能只修改 README 代替它。

这里的“Codex 全破甲”为项目名称，“面向 GPT-6 Astra”描述使用场景。当前功能为本地指令配置、身份迁移、原文件保留、备份和恢复；没有 GPT-6 Astra 模型端兼容性或能力提升验证记录，也不内置扫描、利用或逆向分析引擎。发布介绍与实际实现保持一致。

## 已有工具仓库：升级与更新首页

v1.3.4 修复旧安装记录与当前引用不一致导致安装中止的问题：按当前有效来源重建，本地历史目录保留旧记录、旧指令、修复前配置及原首次备份；卸载恢复到本轮修复前的引用。相对路径统一按 CODEX_HOME 解析，并增加来源与并发校验。也包含此前的“小怪”身份迁移与普通问候修复。

安装用户完整解压新版后，直接再次运行启动 CMD，不要只替换 CMD 或删除旧状态。同步以下 10 个路径，保持子目录结构：

```text
README.md
README.txt
oneclick.py
config_engine.py
验证记录.txt
小怪破甲安装器.exe
tests/test_oneclick.py
tests/test_reference_repair.py
docs/UPLOAD.md
downloads/xiaoguai-oneclick-v1.3.4.zip
```

`README.md` 必须位于仓库根目录。可分别进入根目录、`tests/`、`docs/`、`downloads/` 的 Upload files 页面上传对应文件，不要把子目录文件传到根目录。原有两个 CMD、`test_config_engine.py`、`assets/` 图片和其他未变文件保留。

不要上传真实 `.codex` 目录、用户原指令、安装状态、`history/`、配置快照或本机日志。安装包只包含公开源码、测试、EXE、CMD 和说明。

保留 `downloads/xiaoguai-oneclick-v1.3.2.zip` 和 `downloads/xiaoguai-oneclick-v1.3.1.zip` 作为历史下载，不用新版本内容覆盖旧包。

## 新仓库：上传完整结构

1. 在 `xiaoguai009` 账号下创建并打开 [codex-armor-toolkit](https://github.com/xiaoguai009/codex-armor-toolkit)，使用 **Add file → Upload files**。
2. 将上传材料目录里的文件和子目录拖入上传区，不要把整个外层目录再套一层。
3. 检查 `README.md`、`oneclick.py`、`config_engine.py`、两个 CMD 和 EXE 都直接位于仓库根目录。
4. 保留 `assets/`、`downloads/`、`docs/`、`tests/` 的目录结构；不要再放入旧的 `tool/` 目录。
5. 填写提交说明并提交。这一步才会把所选内容发布到目标仓库。

中文 CMD 和 `小怪破甲安装器.exe` 需要位于同一目录。上传材料同时包含 `README.txt`、`验证记录.txt`、附带文本文件和构建依赖文件，以及当前 v1.3.4 与历史 v1.3.2 / v1.3.1 三个下载包。

## 发布后检查

- 仓库 **About / Description** 显示上述简介，包含 Codex 全破甲、GPT-6 Astra、渗透测试、逆向分析与开发工作流。
- 首页标题为“小怪 · Codex 全破甲”，保留 What、Highlights、Quick Start、Options、Verify、Undo、Layout、Contact 结构。
- 首页自动显示根目录 `README.md`，而不是只显示文件列表。
- “下载 v1.3.4”链接能打开 `downloads/xiaoguai-oneclick-v1.3.4.zip`；v1.3.2 / v1.3.1 安装包仍保留为历史下载。
- README 最底部两张原图并排显示，点击可查看完整图片。
- TG 链接为 [@XGYYDS789](https://t.me/XGYYDS789)，QQ 群号为 **1019953986**。
- 确认口令为 `今宵不见儿童怪，应随斗柄西山外。` 与 `频道@XGYYDS789    QQ群1019953986` 两行，中间仅一个换行，第二行频道与 QQ 群之间恰好为 4 个 ASCII 空格。
- 仅输入 `hi` / `你好` 等纯问候时，预期回复“「你好」”和“小怪在。👋”两行；混合任务不触发短回复。
- 当前工具文件为 v1.3.4，v1.3.2 / v1.3.1 历史安装包保留；项目结构与 README 的目录树一致。
- 根目录 EXE 与 ZIP 内 EXE 字节一致；安装器 SHA256 与验证记录一致。
- 隔离配置下完成引用修复、重复安装与恢复验证；上传后核对上述 10 个远端文件与本地发布文件逐字节一致。

上传时只添加或替换此次整理的文件，不需要删除目标仓库中不相关的文件。
