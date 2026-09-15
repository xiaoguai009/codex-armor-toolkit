# 小怪 · Codex 全破甲 / GitHub 上传说明

当前本地发布材料：**Windows v1.4.0 · Mac v1.4.0-mac.1**。

## 目标与发布状态

- 已有目标仓库：[xiaoguai009/codex-armor-toolkit](https://github.com/xiaoguai009/codex-armor-toolkit)。
- 保持根目录 README、双平台下载入口、原有 TG / QQ 群及底部两张图片。
- 本地编辑、构建或测试不等于 GitHub 已发布；是否同步以远端实际提交和文件核验为准。

## 本次介绍与实际能力

保留项目名称“Codex 全破甲”和面向 GPT-6 Astra 的使用场景，不把名称当作云端审核绕过或模型能力提升证明。

新增的是 ACE 待资料模板、同一任务的资料续接提示词、减少指令误回显规则和只读脱敏暴露检查。**没有可执行 ACE 绕过、没有后台监控、没有本机防提取或防抓包保证。** 简介与 README 不得将这些未实现能力写成已经支持。

可用简介：

```text
Codex 全破甲｜面向 GPT-6 Astra 的本地指令配置工具，支持 Windows / Mac、ACE 资料准备、提示词暴露检查与备份恢复。
```

## 文件同步

同步新版本源码、文档、测试、新 EXE 和两个新 ZIP，保持以下相对位置。没有变化的原有文件保留，不删除远端无关内容。

```text
README.md
README.txt
oneclick.py
task_support.py
privacy_check.py
build_windows_package.py
小怪破甲安装器.exe
准备ACE资料.cmd
检查提示词暴露.cmd
准备ACE资料.command
检查提示词暴露.command
验证记录.txt
macos/run.py
macos/launch.sh
macos/build_package.py
macos/README.md
macos/验证记录.txt
tests/test_oneclick.py
tests/test_reference_repair.py
tests/test_macos_entry.py
tests/test_macos_shell.py
tests/test_macos_package.py
tests/test_support_features.py
tests/test_privacy_check.py
tests/test_windows_package.py
docs/ACE-AND-PRIVACY.md
docs/UPLOAD.md
downloads/xiaoguai-oneclick-v1.4.0.zip
downloads/xiaoguai-oneclick-v1.4.0-mac.1.zip
```

源码根目录仍需要原有 config_engine.py、Windows 安装/卸载 CMD、三个原有 Mac .command、运行时脚本及其他测试。新 CMD 必须与新 EXE 位于同一目录；仅改 Python 源码不会更新已下载的旧 Windows EXE。

保留 v1.3.4、v1.3.4-mac.1、v1.3.2、v1.3.1 历史 ZIP，不用新版本覆盖旧包。底部 assets/support.jpg 和 assets/qq-group.jpg 不变。

## 本地重建

在独立构建环境安装 build-requirements.txt 后执行：

```powershell
python -m PyInstaller --onefile --console --noupx --name 小怪破甲安装器 oneclick.py
# 将 dist 中的新 EXE 复制到项目根目录，再运行回归。
python -B -m unittest discover -s tests -v
python -B build_windows_package.py
python -B macos/build_package.py
python -B build_windows_package.py --check
python -B macos/build_package.py --check
```

两个打包器只收集明确的公开文件白名单，默认拒绝覆盖已经存在的当前版本 ZIP。不要为了打包清理用户配置；不要上传 .codex、真实原指令、认证文件、安装状态、history、日志、构建缓存或本轮源码备份。

.gitignore 不会让已提交到 GitHub 的内容变成秘密。已公开的内置提示词本来就可以直接读取，不应宣传为加密保密内容。

## 发布后核验

1. 两个新下载链接可访问，下载文件 SHA256 与本地发布记录一致。
2. 根目录 EXE 与 Windows ZIP 内 EXE 字节一致；Mac ZIP 保持独立、无 CMD/EXE，.command / .sh 保持 Unix 0755。
3. 新模板与暴露检查在隔离配置下可运行，输出不包含提示词或代理凭据；安装、重复安装、引用修复和恢复仍通过。
4. 首页明确 ACE 为待资料提示词，不写“已实现绕过”或“无法提取”；Mac 实机和模型端效果仍标为未验证。
5. TG 为 [@XGYYDS789](https://t.me/XGYYDS789)，QQ 群 **1019953986**，底部两张原图保留。
6. 精确确认口令仍为两行，第二行中间恰好 4 个 ASCII 空格：

```text
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789    QQ群1019953986
```
