# ModuleSafety：C++20 模块安全子集 / C++20 Module Safety Subset

独立的实验性 Clang 扩展，与 LLVM、Circle 和 Safe C++ 官方无隶属或背书关系。
自有编译器／工具采用 **GPL-2.0-only**；自有公开头文件、运行库和示例采用
**Apache-2.0 WITH LLVM-exception**，std2 改编部分保留 **BSL-1.0**。
详见 [许可范围](LICENSING.md)、[第三方声明](THIRD_PARTY_NOTICES.md) 和
[源码发布／新克隆复现步骤](docs/PUBLISHING.md)。

安全类型体系的分层、开发顺序与验收要求见
[SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md)。

逐特性兼容清单、当前二进制证据及开放缺口见
[compatibility/README.md](compatibility/README.md)。

四项统一验收与运行语义边界见 [FOUR-PILLARS.md](FOUR-PILLARS.md)。
可执行 `python3 tools/accept_four_pillars.py --jobs 4` 构建并验收当前源码和二进制。

See [SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md) for safety type-system
layers, development order and acceptance criteria.

2026-10-23 的阶段使用范围、原样官方库示例和重现命令见
[SAFETY-USAGE.md](SAFETY-USAGE.md)。历史验证与实现记录见
[IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md)。完整 Circle 兼容尚未达到；
历史通过记录不能替代当前二进制的验收。

For the validated scope as of 2026-10-23, unmodified official-library examples,
and reproduction commands, see [SAFETY-USAGE.md](SAFETY-USAGE.md). Historical
implementation and verification records are in
[IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md). Full Circle compatibility
has not been achieved; historical passes do not validate the current binary.

Circle 对齐进展和原生 `T^`／`^owner`、`^^owner`、`:=` 语法的当前边界见
[CIRCLE-COMPATIBILITY.md](CIRCLE-COMPATIBILITY.md)。现有检查器能力不代表完整 Circle 兼容。

See [CIRCLE-COMPATIBILITY.md](CIRCLE-COMPATIBILITY.md) for Circle alignment and
the current boundaries of native `T^` / `^owner`, `^^owner`, and `:=` syntax.
Existing checker capabilities do not establish full Circle compatibility.

项目包含 Clang 22.1.2 AST 插件、共用的 CFG 检查器、检查型运行库，以及可重现的 Clang 原生语法补丁。参考 [Circle](https://github.com/seanbaxter/circle) 和 [Safe C++ D3390](https://safecpp.org/draft.html)。safe 模块默认检查，unsafe 模块的接口默认要求显式 unsafe 调用。safe 函数内部使用 unsafe 不会改变函数的对外安全分类；unsafe 块中的 lambda 和其他函数体会重新进入自己的安全上下文。

The project includes a Clang 22.1.2 AST plugin, a shared CFG checker, a checked
runtime, and a reproducible native-syntax patch for Clang. References are
[Circle](https://github.com/seanbaxter/circle) and
[Safe C++ D3390](https://safecpp.org/draft.html). Safe modules are checked by
default; interfaces from unsafe modules normally require explicit unsafe calls.
Using unsafe internally does not change a safe function's public classification.
Lambdas and other function bodies inside an unsafe block enter independent
safety contexts.

这是一个采取保守拒绝策略的 C++ 子集。测试通过不是整个 C++ 对象模型无 UB 的形式化证明。unsafe 实现必须满足其封装的初始化、生命周期、别名及线程安全条件。此实现不等同于 Circle 或 Rust 的完整语言。

This is a conservatively checked C++ subset. Passing tests is not a formal
proof that the entire C++ object model is free of undefined behavior (UB).
Unsafe implementations must uphold their initialization, lifetime, aliasing,
and thread-safety obligations. This implementation is not the full Circle or
Rust language.

## 构建插件 / Build the Plugin

需要匹配的 LLVM/Clang 开发库。macOS arm64 使用 Homebrew LLVM 22.1.2：

Matching LLVM/Clang development libraries are required. On macOS arm64, use
Homebrew LLVM 22.1.2:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm
cmake --build build
ctest --test-dir build --output-on-failure
python3 tools/build_modules.py examples/modules.json \
  --clang /opt/homebrew/opt/llvm/bin/clang++ --plugin build/ModuleSafety.so
```

插件必须与加载它的 Clang 使用兼容 ABI；Apple 系统 Clang 不能加载 Homebrew LLVM 的插件。

The plugin and the Clang loading it must have compatible ABIs. Apple's system
Clang cannot load a plugin built against Homebrew LLVM.

## 构建原生前端 / Build the Native Frontend

下载并解压官方 `llvm-project-22.1.2.src.tar.xz` 到仓库根目录。补丁在 `frontend/clang-22.1.2.patch`，构建脚本会应用补丁，并将 `src/` 中的共用检查器编入 clangFrontend。使用已安装的 LLVM 动态库，只重建 Clang：

Download and extract the official `llvm-project-22.1.2.src.tar.xz` into the
repository root. The build script applies `frontend/clang-22.1.2.patch` and
compiles the shared checker from `src/` into clangFrontend. It reuses installed
LLVM shared libraries and rebuilds only Clang:

```sh
python3 tools/build_frontend.py --jobs 4
python3 tools/test_frontend.py --jobs 8
python3 tools/build_modules.py examples/native-modules.json \
  --clang llvm-build/bin/clang --native --output native-module-build
llvm-build/bin/clang++ -std=c++20 -fprebuilt-module-path=native-module-build \
  examples/main.cpp native-module-build/native_example.o native-module-build/safety.o \
  -o native-module-build/example
native-module-build/example
```

原生入口由编译命令选择模式：`-fcircle-safety`（等价拼写 `-fmodule-safe`）按 safe 检查整个翻译单元或单个模块，`-fmodule-unsafe` 编译一个已审计的 unsafe 单元。被选中的单元里每个函数定义都按 safe 检查，不需要 `#feature on safety`，也不需要策略文件。`-fmodule-safety-policy=文件` 仍可选：给出时用于把主接口、分区、实现单元和导入的 PCM 模式与整个工程交叉核对，但从不决定是否开启检查。两个模式不能同时使用。原生解析器直接解析 `unsafe {}` 与前置 `unsafe_fn`，不使用这两个名字的预处理宏。

Compiler flags select the native mode: `-fcircle-safety` (also spelled
`-fmodule-safe`) checks the entire translation unit or individual module as
safe; `-fmodule-unsafe` compiles an audited unsafe unit. Every function
definition in the selected safe unit is checked, without requiring
`#feature on safety` or a policy file. The optional
`-fmodule-safety-policy=FILE` cross-checks main interfaces, partitions,
implementation units, and imported PCM modes against the project, but never
decides whether checking is enabled. The two modes are mutually exclusive.
The native parser recognizes `unsafe {}` and prefix `unsafe_fn` directly,
without preprocessor macros for these names.

```cpp
export module example;

unsafe_fn unsigned raw(unsigned* p) { return *p; }

export unsigned wrapper(unsigned& value) {
  unsafe { return raw(&value); }
}
```

插件入口接受 `safe` 或 `unsafe`，以及可选的 `policy=文件` 插件参数。插件使用宏兼容语法，也支持 `include/module_safety.h` 中的 `SAFETY_UNSAFE` / `SAFETY_UNSAFE_FN`。需要工程级模式一致性时，应使用构建器生成的策略；只提供裸模式参数的插件调用不能检查尚未导入的独立分区。

The plugin accepts `safe` or `unsafe`, plus an optional `policy=FILE` argument.
It uses macro-compatible syntax and supports `SAFETY_UNSAFE` /
`SAFETY_UNSAFE_FN` from `include/module_safety.h`. Use a builder-generated
policy for project-wide mode consistency: a bare-mode plugin invocation
cannot check independent partitions that have not been imported.

## 原生安全函数类型与返回借用 / Native Safe Function Types and Returned Borrows

safe 模块的函数类型自动携带安全效果。普通函数指针可以接收安全函数，但丢掉效果后只能在 unsafe 块中调用；unsafe 函数不能隐式升级成安全指针。安全间接调用对空指针生成 trap。

Function types in safe modules automatically carry a safety effect. Ordinary
function pointers may receive safe functions, but after losing the effect they
can only be called inside unsafe blocks. Unsafe functions cannot implicitly
convert to safe pointers. Safe indirect calls trap on null pointers.

```cpp
using Safe = unsigned __attribute__((safe_function)) (unsigned);
using Borrow = const unsigned&
    __attribute__((safe_function, returns_borrow(0))) (const unsigned&);
```

`returns_borrow` 使用从零开始的参数索引，要求返回类型与指定参数均为引用。它属于函数类型身份，并随 PCM 保存；不同借用来源不能互相隐式转换。已有的 `SAFETY_RETURNS_BORROW(x)` 声明在原生前端中也形成该类型信息。检查器验证函数体返回来源，并将间接调用所得引用关联到相应实参，检查所有者销毁和借用冲突。重声明继承契约时只匹配同一函数签名。以上类型扩展需要原生前端，普通 Clang 的 AST 插件没有该类型表示。

`returns_borrow` uses zero-based parameter indices and requires reference types
for both the result and the named parameter. It is part of function-type
identity and survives PCM serialization; different borrow sources cannot
implicitly convert to each other. Existing `SAFETY_RETURNS_BORROW(x)`
declarations also create this type information in the native frontend. The
checker validates return sources and relates references from indirect calls
to the corresponding arguments, checking owner destruction and borrow
conflicts. Contract inheritance across redeclarations only matches the same
function signature. These type extensions require the native frontend; the
ordinary Clang AST plugin has no equivalent type representation.

## 对象生命周期与线程类型规则 / Object Lifetimes and Thread Type Rules

借用作为对象状态传播：引用字段、嵌套对象、基类、数组字段、构造函数、复制和移动都关联到实际所有者。共享借用允许复制；含独占借用的对象禁止复制，移动后原对象不可用。再借用记录父子关系，子借用存活时禁止冲突的父借用操作。非平凡析构会延长借用至析构完成。引用捕获及捕获借用对象的闭包也携带借用；返回局部所有者的借用会被拒绝。

Borrows propagate as object state: reference fields, nested objects, bases,
array fields, constructors, copies, and moves remain related to their actual
owners. Shared borrows may be copied; objects carrying exclusive borrows may
not, and moved-from objects cannot be used. Reborrows record parent-child
relationships and prohibit conflicting parent operations while a child is
live. Nontrivial destruction can keep borrows live through cleanup. Closures
with reference captures or captured borrowing objects also carry borrows;
returning a borrow of a local owner is rejected.

返回对象可以声明多个参数来源；原生函数类型与 PCM 同时保存这些来源。多个来源支持参数索引 0–30。只有一个来源时不受该位图限制。构造函数声明与定义分开时，使用 `SAFETY_STORES_BORROW(x)` 声明其保存的参数借用，定义会被验证。未提供契约且不可见的构造函数体不能被假定具有正确的对象借用来源。带非平凡析构的借用对象不能直接套用 Rust 的移走后不再析构规则；其移动需要有效的移动后析构策略，已审计的清空堆存储实现使用 `unsafe.moved.drop` 标记。全局借用初始化也被检查，不能保存短命对象或其他线程的局部存储引用。

Returned objects may declare multiple parameter sources, preserved in native
function types and PCMs. Multiple sources support parameter indices 0-30;
a single source is not subject to that bitmap limit. When a constructor's
declaration and definition are separate, `SAFETY_STORES_BORROW(x)` declares
the parameter borrows it stores, and the definition is checked. An invisible
constructor body without a contract cannot be assumed to provide valid
object-borrow provenance. Borrowing objects with nontrivial destructors cannot
simply use Rust's no-drop-after-move rule: moves require a valid moved-from
destruction strategy. Audited implementations that empty heap storage use
`unsafe.moved.drop`. Global borrow initialization is also checked and cannot
retain short-lived objects or another thread's local storage.

```cpp
struct View {
  const unsigned& value;
  SAFETY_STORES_BORROW(x) View(const unsigned& x);
};
SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) {
  return View(x);
}
```

`SAFETY_SEND` / `SAFETY_SYNC` 标记参数要求；`SAFETY_SEND_TYPE` / `SAFETY_SYNC_TYPE` 验证记录类型。规则递归检查字段、基类及数组：Send 表示可以在线程间传递，Sync 表示可以共享只读引用。可变引用的 Send 要求其目标为 Send；只读引用的 Send 要求目标为 Sync。只读包装中含可变引用仍有修改能力，不能仅依靠 C++ 的 const 判断。`SAFETY_STATIC_SEND` 进一步禁止传递借用生命周期。

`SAFETY_SEND` / `SAFETY_SYNC` specify parameter requirements;
`SAFETY_SEND_TYPE` / `SAFETY_SYNC_TYPE` validate record types. Rules recursively
check fields, bases, and arrays: Send permits transfer between threads; Sync
permits sharing a read-only reference. A mutable reference is Send only if its
target is Send; a read-only reference requires a Sync target. A read-only
wrapper containing a mutable reference still permits mutation, so C++ const
alone is insufficient. `SAFETY_STATIC_SEND` additionally forbids transferring
borrowed lifetimes.

原始指针、原子存储及未建模的内部可变状态没有自动线程证明。拥有私有指针或同步状态的库可以使用 `SAFETY_UNSAFE_IMPL_SEND` / `SAFETY_UNSAFE_IMPL_SYNC` 提供显式审计的实现，责任与 unsafe 函数封装相同。标量元素 vector 和 mutex 使用此边界；这些标记不能代替所有权及同步实现。

Raw pointers, atomic storage, and unmodeled interior mutability have no
automatic thread-safety proof. Libraries with private pointers or synchronized
state may provide explicitly audited implementations using
`SAFETY_UNSAFE_IMPL_SEND` / `SAFETY_UNSAFE_IMPL_SYNC`, with the same obligations
as unsafe function wrappers. Scalar-element vector and mutex use this boundary;
these markers do not replace ownership or synchronization implementations.

`runtime/threads.cppm` 导出 POSIX 线程模块 `safety_threads`：

`runtime/threads.cppm` exports the POSIX thread module `safety_threads`:

* `std2::run_thread<Target>(value)` 传递不含借用的 Send 值。
* `std2::scoped_thread<Target>(value)` 可以移动带借用的 Send 值，返回前等待线程结束。
* `std2::share_thread<Target>(value)` 共享 Sync 对象的只读引用，返回前等待线程结束。
* `std2::parallel_share<Left,Right>(value)` 同时启动两个工作线程，并在返回前等待二者结束。
* `std2::mutex<T>` 为标量值提供 load、store、update；update 回调抛异常时也释放锁。

* `std2::run_thread<Target>(value)` transfers a borrow-free Send value.
* `std2::scoped_thread<Target>(value)` may move a borrowing Send value and waits for completion before returning.
* `std2::share_thread<Target>(value)` shares a read-only reference to a Sync object and waits before returning.
* `std2::parallel_share<Left,Right>(value)` starts two workers and waits for both before returning.
* `std2::mutex<T>` provides load, store, and update for scalars; update releases the lock even if its callback throws.

线程回调支持 void 或标量结果，经过独立的安全调用函数验证；unsafe 函数或 unsafe 调用运算符不能藏入线程入口。pthread 入口为 noexcept。实现已在 macOS arm64 上运行 ASan/UBSan 和 ThreadSanitizer 测试。

Thread callbacks support void or scalar results and are validated through
independent safe-call helpers. Unsafe functions or unsafe call operators
cannot be hidden in a thread entry point. The pthread entry is noexcept.
The implementation has been exercised with ASan/UBSan and ThreadSanitizer on
macOS arm64.

## 模块构建与信任边界 / Module Builds and Trust Boundaries

只接受 C++20 named module 的接口、接口分区和实现单元。manifest 为每个主模块指定一次模式，分区和实现继承该模式。构建器扫描真实模块声明及 import，验证名称、重复定义、模式、缺失依赖和环路，再按依赖顺序编译 PCM、目标文件和实现单元。配置中的排列顺序不影响构建顺序。

Only C++20 named-module interfaces, interface partitions, and implementation
units are accepted. The manifest selects each primary module's mode once;
partitions and implementations inherit it. The builder scans actual module
declarations and imports, validates names, duplicate definitions, modes,
missing dependencies, and cycles, then builds PCMs, objects, and implementation
units in dependency order. Configuration order does not affect build order.

编译器写入的隐式属性随 PCM 保存，包含模块模式、函数分类和检查器源码指纹（原生模式另绑定已验证的前端补丁摘要）。导入时要求版本及指纹匹配，并拒绝把用户写的同名属性当作编译器证明。缺少元数据的模块不能导入受检查的模块。unsafe 模块不能通过普通导入获得 safe 分类。safe 模块中的前置函数声明可以由该模块的受检查实现单元定义；缺失实现会在链接时失败。全局模块片段中的旧式声明不获得模块信任。显式伪造编译器拥有的 safe/模块属性会报错。

Compiler-generated implicit attributes survive PCM serialization, recording
module mode, function classification, and the checker-source fingerprint
(native mode also binds the verified frontend-patch digest). Imports require
matching versions and fingerprints; user-written attributes with the same
names are not compiler evidence. Modules lacking metadata cannot import
checked modules. Ordinary imports do not upgrade unsafe modules to safe.
Forward function declarations in a safe module may be defined by its checked
implementation units; missing implementations fail at link time. Legacy
declarations in global module fragments do not acquire module trust. Forged
compiler-owned safe/module attributes are diagnosed.

所有生产者应通过同一受检查构建链生成。手工替换 PCM、绕过检查器编译实现，或修改策略和产物，不能成为有效的安全证明。

All producers should use the same checked build chain. Manually replacing
PCMs, compiling implementations without the checker, or modifying policies
and artifacts does not constitute valid safety evidence.

## 检查器与运行库 / Checker and Runtime

* AST 检查拒绝裸指针访问和算术、new/delete、未检查的数组下标、危险转换、显式析构、内联汇编、GNU 间接跳转/语句表达式、VLA、volatile、可变共享状态，以及未知、unsafe 或未携带安全类型的间接函数调用。自动 cleanup、自动初始化回调、符号别名、未建模的优化器前置条件、OpenMP/设备执行均不获得安全许可。原始原子内建操作以及向量、矩阵、复数、定点扩展类型也拒绝，等待相应存储/算术模型。动态有符号溢出、除余和移位通过检查型运行库处理；文字、已物化的 constexpr 数据及立即调用结果中的无 UB 整数常量表达式可以直接使用；普通 constexpr 函数调用的折叠结果不能代替运行时范围证明。
* safe 代码的非 void 函数必须在所有正常退出路径返回值；异常退出和不终止的循环允许，关闭 `-Wreturn-type` 不能绕过此检查。整数转浮点要求整个源类型范围可由目标浮点类型容纳，或者常量表达式已被证明精确可表示，否则要求使用检查型转换（包括显式转换）。例如 `unsigned __int128` 转 `float` 被拒绝，而转 `double` 允许。
* 只对可能改变数值的隐式转换警告：窄化、不能保持全范围的符号变化、可能损失精度的整数/浮点转换。无损扩大、可证明精确的整数常量、bool 判断、函数/数组退化不警告。显式转换仍接受 UB 检查；需要检查的值可用 `try_into` 或 `checked_into`。警告使用稳定的 `-Wbackend-plugin` 诊断组并支持 `-Werror`。
* safe 编译禁用以循环必须终止为前提的优化；原生前端在从 PCM 单独生成代码时也保留此语义。CFG 固定点分析覆盖分支和循环的确定初始化、移动后的使用、共享/独占借用冲突、最后一次使用后释放借用（含结构化绑定）、作用域销毁，以及隐式析构调用。返回引用要求可检查的参数或 this 生命周期契约；检查器验证返回来源、重声明一致性及虚函数覆盖契约。
* 安全模板实例化会检查具体函数体，包括从 PCM 导入的模板。默认构造和构造初始化顺序会检查标量字段的初始化。表达式检查区分实际求值与 sizeof、decltype、noexcept、requires 等未求值上下文。
* 引用字段和引用捕获使用对象借用检查；非标量／非平凡 union、mutable 字段、this 捕获及带外部借用的协程帧仍在 safe 上下文中拒绝；受限标量 union 和拥有型标量 generator 已支持。无法建立引用来源时拒绝，不凭用户属性假定悬垂引用安全。
* `runtime/safety.cppm` 提供 `std2::checked_add/sub/mul/div/rem/shl/shr/cast`、标量元素 `array` / `vector`、受检查的 `move` 、以编译期目标为类型参数的 `callable`，以及带标量参数/结果签名的动态回调 `function<R(Args...)>`。vector 禁用复制，支持移动和检查型扩容；公共读写 API 不暴露元素指针或引用。越界和算术失败在发生 UB 之前 trap。

* AST checks reject raw-pointer access and arithmetic, new/delete, unchecked array indexing, dangerous casts, explicit destruction, inline assembly, GNU indirect jumps/statement expressions, VLAs, volatile storage, mutable shared state, and unknown, unsafe, or untyped indirect calls. Automatic cleanup/initialization callbacks, symbol aliases, unmodeled optimizer preconditions, and OpenMP/device execution receive no safety permission. Raw atomic builtins and vector, matrix, complex, and fixed-point extensions are also rejected pending storage/arithmetic models. Dynamic signed overflow, division/remainder, and shifts use the checked runtime. UB-free integer constant expressions from literals, materialized constexpr data, and immediate calls may be used directly; folding an ordinary constexpr call is not a runtime range proof.
* Non-void safe functions must return a value on every normal exit; exceptional exits and nonterminating loops are allowed. Disabling `-Wreturn-type` cannot bypass this check. Integer-to-floating conversion requires either the entire source range to fit or a constant proven exactly representable; otherwise a checked conversion is required, even for explicit casts. For example, `unsigned __int128` to `float` is rejected, while conversion to `double` is allowed.
* Warnings cover only potentially value-changing implicit conversions: narrowing, sign changes that cannot preserve the full range, and potentially lossy integer/floating conversions. Lossless widening, provably exact integer constants, bool conditions, and function/array decay do not warn. Explicit conversions remain subject to UB checks; use `try_into` or `checked_into` where needed. Warnings use the stable `-Wbackend-plugin` group and support `-Werror`.
* Safe compilation disables optimizations that assume loops must terminate, including native code generation from a PCM. CFG fixed-point analysis covers definite initialization across branches/loops, use after move, shared/exclusive borrow conflicts, expiry after last use (including structured bindings), scope destruction, and implicit destructor calls. Returned references require checkable parameter or this-lifetime contracts; the checker validates return sources, redeclarations, and virtual overrides.
* Safe template instantiations check concrete bodies, including templates imported from PCMs. Default construction and initializer order are checked for scalar-field initialization. Expression checking distinguishes evaluation from unevaluated contexts such as sizeof, decltype, noexcept, and requires.
* Reference fields and captures use object-borrow checking. Non-scalar/nontrivial unions, mutable fields, this captures, and coroutine frames with external borrows remain rejected in safe contexts; restricted scalar unions and owning scalar generators are supported. Unknown reference provenance is rejected rather than treated as safe based on user attributes.
* `runtime/safety.cppm` provides `std2::checked_add/sub/mul/div/rem/shl/shr/cast`, scalar-element `array` / `vector`, checked `move`, `callable` parameterized by a compile-time target, and dynamic `function<R(Args...)>` callbacks with scalar parameters/results. Vector disables copying and supports moves and checked growth; public read/write APIs expose no element pointers or references. Bounds and arithmetic failures trap before UB occurs.

## 显式数值转换 / Explicit Numeric Conversions

`runtime/conversions.cppm` 导出 `safety_conversions`，依赖 `safety`。把两个模块都加入构建 manifest 即可使用：

`runtime/conversions.cppm` exports `safety_conversions`, which depends on
`safety`. Add both modules to the build manifest:

```cpp
import safety_conversions;
auto a = std2::into<unsigned long long>(42u); // 全类型范围无损 / Lossless for the full source range
auto b = std2::into<double>(42u); // 全类型范围无损 / Lossless for the full source range
auto c = std2::try_into<unsigned char>(256u); // c.ok == false
// c.value 始终初始化；失败时为零，使用前应检查 c.ok。
// c.value is always initialized, zero on failure; check c.ok before use.
auto d = std2::checked_into<unsigned char>(255u); // 失败则 panic / Panics on failure
```

`into` 仅在源类型的所有值均可无损转换时参与重载；`try_into` 按具体值检查，成功表示精确保留数值。它支持标准整数（含 128 位扩展）以及 float/double/long double，排除 bool、枚举、指针和用户自定义类。小数转整数、舍入损失、越界返回失败，未执行危险转换；身份和无损扩大允许 NaN/无穷，其他浮点路径拒绝非有限值。`checked_into` 使用同一检查，失败时 trap。它们不会自动重写 C++ 的隐式转换，也没有为内建标量增加 `.into()` 成员语法。

`into` participates in overload resolution only when every value of the source
type converts losslessly. `try_into` checks individual values; success means
exact numeric preservation. It supports standard integers (including 128-bit
extensions) and float/double/long double, excluding bool, enums, pointers, and
user-defined classes. Fractional-to-integer conversion, rounding loss, and
out-of-range values fail without performing a dangerous conversion. Identity
and lossless widening permit NaN/infinity; other floating paths reject
nonfinite values. `checked_into` uses the same checks and traps on failure.
These APIs neither rewrite implicit C++ conversions nor add `.into()` member
syntax to built-in scalars.

safe 静态存储当前要求常量初始化及平凡析构，避免构造/析构顺序和局部 static 重入；复杂静态生命周期需要另行建模。借用型异常载荷、未建模的 packed/pragma pack/欠对齐存储，以及多态对象构造/析构期间的 this 逸出或本对象方法调用会拒绝。`-ffast-math` 和忽略 NaN/无穷的选项不允许用于 safe 模块，以免优化器移除转换检查。

Safe static storage currently requires constant initialization and trivial
destruction to avoid initialization/destruction-order and local-static
reentrancy issues; complex static lifetimes need a separate model. Borrowing
exception payloads, unmodeled packed/pragma-pack/under-aligned storage, and
this escape or calls on the object during polymorphic construction/destruction
are rejected. Safe modules disallow `-ffast-math` and options that ignore
NaN/infinity, preventing optimizers from removing conversion checks.

## 泛型借用堆容器、静态与固定地址存储 / Generic Borrowing Containers, Static and Pinned Storage

`runtime/borrows.cppm` 导出模块 `safety_borrows`，提供 `std2::borrowed_vector<T,Owner>`。T 为只读、可共享的借用对象，构造时显式绑定 Owner 区域。push_back 会检查元素的全部借用来源是否包含在该区域中；容器保留所有者借用至销毁。扩容使用对齐分配和逐元素构造，异常时销毁已构造的元素；复制禁止，移动会清空原堆存储。get 的返回值通过 this 契约关联到容器，存储借用活着时不能扩容。

`runtime/borrows.cppm` exports `safety_borrows` and provides
`std2::borrowed_vector<T,Owner>`. T is a read-only, shareable borrowing object,
explicitly bound to an Owner region at construction. push_back checks that
all element borrow sources belong to that region; the container retains its
owner borrow until destruction. Growth uses aligned allocation and per-element
construction, destroying constructed elements on exceptions. Copying is
disabled; moving empties the original heap storage. A this contract relates
get's result to the container, and growth is prohibited while storage is
borrowed.

库的 `unsafe.mutates.storage` / `unsafe.adopts.borrow` 约定分别表示只改内部存储及接收区域内的借用；这些是明确的库审计边界。它们必须正确实现，检查器不能证明 raw heap 操作自身。元素存储字段用 `unsafe.sequence.storage` 声明：读出的元素借用的是序列声明的区域（对 receiver 即 receiver），因此带 `borrow.this` 契约的取值函数成立；该声明只在审计序列、元素类型携带借用且声明了 `stores.borrow:`/`stores.self` 存储区域时被接受，取值函数的返回来源仍逐条验证。借用对象拥有非平凡析构时，移动还需要有效的移动后析构策略；泛型代码不能假定 C++ 原对象不再析构。

The library's `unsafe.mutates.storage` / `unsafe.adopts.borrow` contracts
describe internal-storage-only mutation and adoption of borrows within a
region. They are explicit library-audit boundaries and must be implemented
correctly; the checker does not prove raw heap operations themselves.
`unsafe.sequence.storage` marks element storage: extracted elements borrow
the sequence's declared region (the receiver for receiver-bound storage),
supporting accessors with `borrow.this`. It is accepted only for audited
sequences whose element type carries borrows and whose storage region is
declared with `stores.borrow:` / `stores.self`; accessor return sources are
still individually checked. Moving a borrowing object with nontrivial
destruction also requires a valid moved-from destruction strategy. Generic
code cannot assume the original C++ object will never be destroyed.

`SAFETY_RETURNS_STATIC` 声明永久、非线程局部的返回借用，函数体会验证其来源，原生函数类型和 PCM 保留这一效果。`SAFETY_PINNED` 类型必须显式删除复制、移动构造，允许直接在固定存储中构造自引用字段。`SAFETY_STORES_SELF` 用于声明与定义分开的 pinned 构造函数；构造体只允许自有存储或声明的外部参数来源。自引用不能逃逸出其存储生命周期。固定地址拥有句柄现由 `safety_ownership` 的 `std2::pin_box<T>` 提供；工厂支持拥有参数，自引用对象必须满足 self-only pinned 构造契约；带外部借用的对象使用 `pin_region<T,Owner>`。

`SAFETY_RETURNS_STATIC` declares a permanent, non-thread-local returned borrow.
Its body is checked and the effect survives native function types and PCMs.
`SAFETY_PINNED` types must explicitly delete copy and move constructors and may
construct self-references directly in fixed storage. `SAFETY_STORES_SELF`
supports separately declared/defined pinned constructors, whose bodies may
use only owned storage or declared external parameter sources. Self-references
cannot escape their storage lifetime. `std2::pin_box<T>` in `safety_ownership`
provides a pinned owning handle. Factories support owning parameters;
self-referential objects must satisfy a self-only pinned construction
contract. Objects with external borrows use `pin_region<T,Owner>`.

## 验证范围与限制 / Verification Scope and Limitations

回归包括编译成功/拒绝、跨模块元数据、分区与实现、独立策略冲突、模板实例化、初始化和借用、构造顺序、移动与析构、编译/链接/执行，以及 ASan/UBSan 下的容器和算术检查与故意触发的 14 种 panic。原生前端另验证无需插件加载、原生 token 未被宏替换、强制策略和模式互斥和优化后的循环进展语义。

Regressions cover accepted/rejected compilation, cross-module metadata,
partitions and implementations, independent policy conflicts, template
instantiation, initialization and borrowing, construction order, moves and
destruction, compile/link/run behavior, and container/arithmetic checks under
ASan/UBSan, including 14 intentionally triggered panic cases. Native frontend
tests additionally cover operation without plugin loading, native tokens not
replaced by macros, enforced policies, mutually exclusive modes, and optimized
loop-progress semantics.

对象借用及 Send/Sync 检查现已提供，但尚未达到 Circle 完整类型系统的覆盖：借用堆容器支持显式 Owner 区域下的只读和混合可变元素，固定地址自引用支持直接构造和 pin_box 拥有句柄，原子支持整数、bool、指针及五种内存序。命名生命周期、泛型交集和编译期高阶借用回调已实现；Rust 全部高阶量化/GAT/方差规则、任意协程／union，以及整个 C++ 标准 UB 清单的形式化覆盖仍未完成。上述能力不能用通过现有测试来代替。需要这些能力时，必须进一步扩展前端及检查器；当前不受支持的功能应被拒绝或进入明确的 unsafe 审计边界。

Object-borrow and Send/Sync checking are available, but do not cover Circle's
full type system. Borrowing heap containers support read-only and mixed mutable
elements within explicit Owner regions; pinned self-references support direct
construction and pin_box owning handles; atomics support integers, bool,
pointers, and five memory orders. Named lifetimes, generic intersections, and
compile-time higher-order borrowing callbacks are implemented. Full Rust-style
higher-ranked quantification/GAT/variance rules, arbitrary coroutines/unions,
and formal coverage of the C++ standard's entire UB catalog remain incomplete.
Passing current tests cannot substitute for these capabilities. They require
further frontend/checker work; unsupported features should be rejected or
placed behind an explicit audited unsafe boundary.

转换范围模型已有 1,368 个 Z3 验证条件全部 UNSAT；证明边界见 [SAFETY-MODEL.md](SAFETY-MODEL.md)。这没有证明整个检查器或 C++ 编译链。

All 1,368 Z3 verification conditions for the conversion-range model are UNSAT.
See [SAFETY-MODEL.md](SAFETY-MODEL.md) for proof boundaries. This does not prove
the entire checker or C++ compilation chain.

当前验证结果及复现命令见 [VERIFICATION.md](VERIFICATION.md)。

Current verification results and reproduction commands are in
[VERIFICATION.md](VERIFICATION.md).

生产候选版本的验证流程、新增 API 及支持边界见 [PRODUCTION.md](PRODUCTION.md)。

See [PRODUCTION.md](PRODUCTION.md) for the production-candidate verification
process, additional APIs, and support boundaries.

命名生命周期、作用域回调、Pin 借用/投影/取出和完整原子操作接口见 [LIFETIMES-AND-CONCURRENCY.md](LIFETIMES-AND-CONCURRENCY.md)。

See [LIFETIMES-AND-CONCURRENCY.md](LIFETIMES-AND-CONCURRENCY.md) for named
lifetimes, scoped callbacks, Pin borrowing/projection/extraction, and the full
atomic-operation interface.

## 泛型 unsafe 边界及运行时常量 / Generic Unsafe Boundaries and Runtime Constants

泛型拥有容器必须分别验证元素的复制／移动、析构和回调的安全效果；noexcept 只描述异常，不能授权调用 unsafe_fn。借用容器和 Pin 拥有器使用独立 safe 帮助函数进行实例化验证；mutex 的对象回调也通过同样的边界验证。Pin 分配／释放使用全局限定的 ::new / ::delete，不调用 T 的类专属分配／释放函数。

Generic owning containers must independently validate the safety effects of
element copy/move operations, destruction, and callbacks. noexcept describes
exceptions only and cannot authorize unsafe_fn calls. Borrowing containers
and Pin owners use independent safe helpers for instantiation checks; mutex
object callbacks use the same boundary. Pin allocation/deallocation uses
globally qualified ::new / ::delete, not T's class-specific allocation functions.

unsafe 断言（包含 unsafe.impl.send/sync、moved.drop、堆存储／借用接收、协程 promise／suspend 标记）都是需要审计的实现义务，不是编译器证明。普通 constexpr 调用可能观察编译期环境，因此不以其折叠结果免除运行时算术及转换检查；文字、constexpr 已物化数据和 consteval 立即调用结果仍可作为稳定常量。

Unsafe assertions, including unsafe.impl.send/sync, moved.drop, heap-storage
and borrow-adoption contracts, and coroutine promise/suspend markers, are
implementation obligations requiring audit, not compiler proofs. Ordinary
constexpr calls may observe the compile-time environment, so their folded
results do not waive runtime arithmetic/conversion checks. Literals,
materialized constexpr data, and consteval immediate-call results remain
usable as stable constants.

weak/weak_import、naked/returns_twice 不能提供 safe 调用保证；未验证的 pure/const、分配大小／对齐和非空优化承诺同样拒绝。C++ noexcept（包括 Clang 将 GNU nothrow 规范化为异常规范的情况）保留语言规定的终止语义。

weak/weak_import and naked/returns_twice cannot provide safe-call guarantees.
Unverified pure/const, allocation-size/alignment, and nonnull optimization
promises are also rejected. C++ noexcept, including GNU nothrow normalized
by Clang into an exception specification, retains language-defined termination
semantics.


### Circle 兼容的外层区域捕获与关联类型

嵌套回调可以引用外层函数的区域；它自己的绑定仍然独立，例如：

```cpp
const unsigned^/a invoke/(a)(const unsigned^/a input,
    const unsigned^/a callback/(b)(const unsigned^/b) safe) safe {
  return callback(input);
}
```

这里 `a` 来自外层，`b` 由每次回调调用独立选择。类的 `T+` 实参也可承载回调的
自由区域，类字段据此组合协变、逆变、不变及未使用参数的双变；可变存储保持不变。
关联类型投影保留模板参数与包元素身份，包含别名链、偏特化、嵌套／继承的关联别名、
成员别名模板及包索引元函数。无法证明的映射继续拒绝借用操作。

这些规则按本仓库的 Circle 兼容扩展定义。设计、正反例和范围见
[安全架构说明](SAFETY-ARCHITECTURE.md#circle-兼容捕获与泛型关系扩展2026-10-27)。
完整回归包含 `outer_region_captures.py`、`class_parameter_variance.py`、
`captured_callable_values.py` 和扩展的 `generic_region_projection.py`。
