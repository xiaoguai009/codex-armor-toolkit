# Mac 独立 Python 运行时

启动器优先复用已有 Python 3.11+；仅在找不到合格解释器时下载运行时。

- 上游：https://github.com/astral-sh/python-build-standalone
- 固定发布：https://github.com/astral-sh/python-build-standalone/releases/tag/20260901
- Python：3.12.14
- 官方校验表：https://github.com/astral-sh/python-build-standalone/releases/download/20260901/SHA256SUMS

| 架构 | 文件 | SHA256 |
| --- | --- | --- |
| Apple Silicon / arm64 | cpython-3.12.14+20260901-aarch64-apple-darwin-install_only_stripped.tar.gz | `81a359f1cfadd4da11766534c5913791cea55f26e1bb902cacd2a531bb1e4b2b` |
| Intel / x86_64 | cpython-3.12.14+20260901-x86_64-apple-darwin-install_only_stripped.tar.gz | `65b195c9cedc1fef6767f044f9822069adbd1bd9204d424ece4628776fdc04bb` |

这些 URL 与 SHA256 同时固定在 `runtime-pins.sh`，不使用动态 latest 下载地址。经 HTTPS 下载并核对 SHA256 后才解压或执行；打包前另核对这两个精确压缩包的所有成员及链接都位于 `python/` 内。

运行时保留上游自带的全部许可证文件，包括 `python/lib/python3.12/LICENSE.txt` 及所附依赖的许可证；本项目不改写这些文件，也不把上游的许可归属改为本项目。

缓存按 Python 版本、发布号和架构区分。创建独立临时目录，校验、自检后整体提交；每次复用会核对缓存记录和解释器摘要，并测试所需标准库。缓存损坏时保留现场报错，不覆盖用户 Python。锁竞争有限等待，不自动删除其他操作的锁。

Apple Silicon（含 Rosetta 终端）优先选原生 arm64；Intel 选择 x86_64。两个运行时均已下载并核对 SHA256、目录/链接和 Mach-O 元数据；尚未执行 Mac 原生自检。
