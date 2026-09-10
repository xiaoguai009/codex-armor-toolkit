小怪破甲 · CMD 自动版 1.3.2

使用
1. 完整解压，双击“启动小怪破甲.cmd”。
2. 自动定位配置目录、保存备份、保留现有指令并追加“小怪”确认口令。
3. 自动请求打开 Codex；在新任务中输入：小怪
4. 预期只回复下面两行，中间仅一个换行；频道与 QQ 群之间恰好为 4 个 ASCII 空格：
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789    QQ群1019953986

1.3.2 更新：确认回复的第二行新增 QQ 群。已有 1.3.0 / 1.3.1 安装可直接再次运行启动 CMD，
仅更新原口令块，保留其他指令正文及首次备份；之后在 Codex 新任务中验证。

不再弹出选档窗口，无需选择配置或点击安装。无需另装 Python，无需下载依赖。
CMD 和“小怪破甲安装器.exe”放在同一目录，支持中文和空格路径。
小怪破甲 1.2.0 原悬浮窗 EXE 保持不变；本版替换的是 CMD 启动工作流。

实际工作原理
和参考安装器一样，通过 config.toml 的顶层 model_instructions_file 加载指令文件。
若已存在有效指令文件，完整保留原正文，只在副本末尾追加精确口令。
没有原指令引用时，使用内置“开发增强”基础正文。
安装不改 Codex 程序、模型设置、账号或 API 密钥，也不强制结束 Codex。
“本地配置已写入”不等同于“模型已回复”；以 Codex 实际返回上述两行为确认。
已有任务可能保留创建时的指令；优先使用新任务，如仍未载入则退出并重新打开 Codex。
安装包本身不附带或分发本机原有的自定义指令。

配置位置
优先使用环境变量 CODEX_HOME，否则使用 %USERPROFILE%\.codex。
安装状态与副本位于 CODEX_HOME\managed-prompts\xiaoguai-oneclick\。
首次备份为 config.toml.before-oneclick.bak；重复双击不覆盖首次备份。
与旧版 xiaoguai 目录及参考工具的状态文件隔离，旧文件均保留。

恢复
双击“卸载小怪破甲.cmd”，仅恢复安装前的指令引用；之后新增的其他设置保留。
未修改的工具文件清理，手动改过的指令文件保留。可重复卸载。
如果安装后另一个工具改了当前引用，停止覆盖并保留原配置与备份。

命令行参数
小怪破甲安装器.exe --install --no-open --json
小怪破甲安装器.exe --status --json
小怪破甲安装器.exe --restore --json
可追加 --codex-home "C:\路径\测试配置目录" 指定隔离配置。
源码要求 Python 3.11+，运行 oneclick.py；EXE 已内置运行时。
源码测试：python -B -m unittest discover -s tests -v
重新构建：安装 build-requirements.txt 中的构建依赖后，在工具目录执行：
python -m PyInstaller --onefile --console --noupx --name 小怪破甲安装器 oneclick.py

验证范围见“验证记录.txt”。
