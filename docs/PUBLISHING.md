# 发布源码到 GitHub

本项目使用分区许可：编译器／工具的自有部分为 **GPL-2.0-only**；自有公开头文件、
运行库和示例为 **Apache-2.0 WITH LLVM-exception**；std2 改编部分保留 **BSL-1.0**。
完整范围见 [LICENSING.md](../LICENSING.md) 与
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 使用独立的公开仓库

开发仓库的旧提交含 C++ 标准草案原文。仅在新提交中删除它，仍会把旧版本随历史
推送。因此首次公开采用**当前源码快照的新仓库**，不复制开发仓库的 `.git`。
原开发目录、实验文件和历史保留在本机；不对它们执行强推、清理或历史重写。

在开发仓库运行：

```sh
python3 tools/prepare_public_source.py
python3 tools/prepare_public_source.py --output build/github-public
```

脚本使用明确的源码范围，拒绝未分类文件、符号链接、二进制、超大文件、部分已知
凭据模式以及补丁摘要不匹配。已存在的输出目录会被拒绝，避免覆盖编辑过的发布副本。
`SOURCE-MANIFEST.json` 记录每个导出文件的 SHA-256；它是内容清单，不是法律清白
或没有秘密的证明。未复制下载资料、标准原文、工具链、构建产物、临时探针、内部
工作提示和旧 Git 历史。它不保证识别所有形式的敏感数据或第三方来源问题。

若发布目录还没有初始化 Git，可在其中审阅并提交：

```sh
cd build/github-public
git init -b main
git add --all
git diff --cached --stat
git diff --cached --check
git commit -m "Prepare initial public source release"
```

这里的 `git add --all` 仅用于**经过导出的独立目录**。不要在原开发仓库照搬。
提交使用本机 Git 身份；需要隐藏联系邮箱时，在提交前自行设置 GitHub 提供的
noreply 地址。不要擅自替换已有提交的作者。

然后在 GitHub 新建**空仓库**，不要在线生成 README 或另一份许可证。在这个新仓库
目录中配置真实地址并推送：

```sh
git remote add origin git@github.com:YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

用真实账号与仓库名称替换占位符。公开发布前确认使用的是导出仓库，且
`git rev-list --count HEAD` 对首次快照为 `1`。不要对原开发仓库直接执行此推送步骤。
GitHub 仓库可先设为 private 以审阅待公开内容；private 本身不会解决许可义务。

后续可直接在公开仓库继续开发，也可把开发仓库的新改动导出到另一个新目录，审查
差异后作为普通提交引入公开仓库。保留公开仓库 `.git`，不要用开发 `.git` 替换它，
也不要反复创建新的公开根提交或强推。

## 新克隆后的依赖与复现

需要 Python 3.11+、Git、CMake、Ninja 和匹配的 LLVM/Clang 开发库。当前完整验收
环境为 macOS arm64、LLVM/Clang 22.1.2；其他环境不能据此视为已验收。

按需获取固定参考输入，下载结果保留在已忽略的本地目录：

```sh
python3 tools/fetch_references.py safe-cpp circle mdspan n4861 llvm
tar -xf downloads/llvm-project-22.1.2.src.tar.xz
python3 tools/build_frontend.py --jobs 4
python3 tools/accept_four_pillars.py --jobs 4
```

Circle 仅用于本地参考；没有随项目授予其源码的再分发许可。下载和使用须遵守各自
适用条款。脚本校验固定提交、归档与草案文件摘要，不会自动覆盖已修改输入。
已下载时可加 `--offline` 验证／恢复，无需再次联网。原生构建所需环境和插件构建
见 [README.md](../README.md)；Lean、Z3 等完整验证依赖还需按相应工具说明安装。

标准原文不随源码快照提供；`tools/ub_inventory.py --check` 在取回固定 N4861 输入后
才能运行。历史验收日志位于本地 `build/`，不随此快照发布；新克隆需要自行复现。
`tools/release_check.py` 还要求完整官方兼容门禁，当前未建立完整 Circle 兼容，不能
把四项范围验收称为该门禁已通过。

## 发布范围

本次准备的是源码、源码补丁和许可文件。GPL 编译器二进制的再分发需遵守相应源码
及构建材料义务；打包 LLVM、系统库或其他依赖时，还需核对实际分发的每个组件。
不直接上传开发工具链、SDK、下载缓存或本地构建目录作为二进制 release。

项目名称和说明应表明独立实现身份。保留第三方通知和修改说明；未经证实的
“全兼容”“绝对内存安全”等承诺不应作为发布宣传。
