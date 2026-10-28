# safe-clang

基于 Clang 22.1.2 的实验性 C++20 安全扩展，包含原生语法补丁、共享 AST／CFG
检查器、Clang 插件和检查型运行库。参考 Circle／Safe C++，与其官方及 LLVM
无隶属或背书关系。内部插件和检查器名称仍为 `ModuleSafety`。

safe 模式检查拥有权、共享／独占借用、生命周期、函数效果及运行时边界；
关闭扩展时以保持普通 Clang 行为为目标。当前验收集中在 **macOS arm64**。
完整 Circle 兼容、所有平台 ABI 和端到端内存安全证明尚未建立。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [语言与运行库](docs/LANGUAGE.md) | 编译模式、借用、生命周期、重定位、ABI、choice／tuple／slice 和库接口 |
| [安全模型](docs/SAFETY.md) | 实现分层、不变量、unsafe 审计义务和证明边界 |
| [验证流程](docs/VALIDATION.md) | 四项统一回归、局部证明、模块产物和支持范围 |
| [兼容清单](compatibility/README.md) | 固定参考版本、逐特性元数据、历史证据和开放缺口 |
| [发布说明](docs/PUBLISHING.md) | 源码快照、依赖获取和 GitHub 推送 |

## 构建原生前端

需要 Python 3.11+、Git、CMake、Ninja 及匹配的 LLVM／Clang 22.1.2 开发库。
以下命令使用 macOS Homebrew LLVM 的默认路径；其他环境须调整工具参数。

```sh
python3 tools/fetch_references.py llvm safe-cpp circle mdspan
# 源码归档有固定 SHA-256 校验；只对首次获取的干净源码解压。
tar -xf downloads/llvm-project-22.1.2.src.tar.xz
python3 tools/build_frontend.py --jobs 4
```

构建脚本应用 `frontend/clang-22.1.2.patch`，校验原生源码摘要，并把 `src/` 的
共用检查器编入 Clang。已修改的源码树不能靠重新解压覆盖修复，按脚本诊断处理。

```sh
mkdir -p build
llvm-build/bin/clang++ -std=c++20 -fcircle-safety -fcircle-borrow-values \
  -Idownloads/safe-cpp-reference/libsafecxx/single-header \
  examples/borrowed-catalog/main.cpp -o build/borrowed-catalog
build/borrowed-catalog
```

此例输出 `alpha` 和 `beta`，演示携带借用的容器返回与拥有转移。
另有 [线段树示例](examples/segment-tree/README.md)。

## 编译模式示例

`-fcircle-safety`（别名 `-fmodule-safe`）开启整个翻译单元／模块的检查，
`-fmodule-unsafe` 编译显式 unsafe 单元。可选 policy 文件校验工程内模块模式，
不决定是否开启检查。safe 函数中的 unsafe 块仍由实现者承担底层契约。

```cpp
export module example;

unsafe_fn unsigned raw(unsigned* p) { return *p; }

export unsigned wrapper(unsigned& value) {
  unsafe { return raw(&value); }
}
```

更多原生借用和延迟初始化示例见 [语言说明](docs/LANGUAGE.md)。

## 插件与模块构建

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm
cmake --build build
ctest --test-dir build --output-on-failure
python3 tools/build_modules.py examples/modules.json \
  --clang /opt/homebrew/opt/llvm/bin/clang++ --plugin build/ModuleSafety.so
```

插件必须与宿主 Clang ABI 匹配；Apple 系统 Clang 不能加载 Homebrew LLVM 的插件。
插件只实现可通过属性／宏表达的接口，原生语法和借用类型需要上述补丁前端。

原生模块示例：

```sh
python3 tools/build_modules.py examples/native-modules.json \
  --clang llvm-build/bin/clang --native --output native-module-build
llvm-build/bin/clang++ -std=c++20 -fprebuilt-module-path=native-module-build \
  examples/main.cpp native-module-build/native_example.o native-module-build/safety.o \
  -o native-module-build/example
native-module-build/example
```

## 验证

```sh
python3 tools/accept_four_pillars.py --jobs 4
```

统一入口覆盖区域关系、高阶关系、泛型投影和运行语义，先构建再运行回归，
并绑定源码、二进制及日志摘要。历史通过数量不能代替当前快照重新执行；
完整发布工具还有尚未建立的官方完整兼容门禁。详见 [验证流程](docs/VALIDATION.md)。

## 许可证

自有编译器／工具采用 **GPL-2.0-only**；自有公开头文件、运行库和示例采用
**Apache-2.0 WITH LLVM-exception**；std2 改编保留 **BSL-1.0**。
见 [许可范围](LICENSING.md) 和 [第三方声明](THIRD_PARTY_NOTICES.md)。
