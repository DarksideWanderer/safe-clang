# 已验证的安全用法 / Validated Safety Usage

当前 macOS arm64 编译器在 O0 和 O2 下支持经过测试的 Circle safety 子集。
这是实验性编译器，不代表完整兼容 Circle，也不证明所有被接受的程序都具备内存安全性。

The current macOS arm64 compiler supports a tested Circle safety subset at
O0 and O2. This is an experimental compiler, not a claim of complete Circle
compatibility or a proof that every accepted program is memory-safe.

## 运行程序 / Run a Program

在仓库根目录执行：

From the repository root:

```sh
./llvm-build/bin/clang --driver-mode=g++ -std=c++20 \
  -fcircle-safety -fcircle-borrow-values \
  -Idownloads/safe-cpp-reference/libsafecxx/single-header \
  -O0 examples/borrowed-catalog/main.cpp -o build/borrowed-catalog
./build/borrowed-catalog
```

程序输出 `alpha` 和 `beta`。它使用未经修改的官方头文件，返回携带借用的容器，
转移所有权，并在容器销毁前复制出元素的视图。应用代码中没有 unsafe 块。

The program prints `alpha` and `beta`. It uses the unmodified official header,
returns a container carrying a borrow, transfers ownership, then copies an
element's view out before its container is destroyed. Its application code
contains no unsafe blocks.

返回携带借用的值时，函数应显式声明生命周期契约。示例通过 `/a` 和 `/(a)`，
将返回的 vector 或 string_view 绑定到输入来源；未知生命周期不能作为擦除依赖的许可。
源数据必须在所有后续使用期间保持存活。

Functions returning borrow-carrying values should spell their lifetime
contracts explicitly. The example binds the returned vector or string view
to its input with `/a` and `/(a)`; an unknown lifetime is not permission to
erase the dependency. Source data must remain alive for every subsequent use.

## 重现验证 / Reproduce the Checks

```sh
python3 tests/safety_composition_review.py
python3 tests/container_factory_regions.py
python3 tests/indirect_storage_replacement.py
python3 tests/indirect_storage_destruction.py
python3 tests/indirect_storage_construction.py
python3 tests/class_lifetime_variance.py
python3 tests/region_relation_entries.py
python3 tests/borrow_capabilities.py
python3 tests/higher_ranked_relations.py
python3 tests/higher_ranked_relation_algebra.py
python3 tests/higher_ranked_pack_substitution.py
python3 tests/official_positive_tests.py
python3 examples/segment-tree/verify.py
python3 tools/test_frontend.py --jobs 4
```

区域入口矩阵将同一组契约用于重声明、虚覆盖、impl、隐式及显式转换，分别检查本地
和 PCM 行为；直接、间接、模板及 impl 调用还检查区域写入约束。高阶回调转换使用独立
绑定作用域，组合共享协变、可变内容不变性及嵌套参数逆变；显式区域参数包展开保留
绑定、约束、类投影和返回来源。详细范围见 [SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md)。

The region-entry matrix applies the same contracts to redeclarations, virtual
overrides, impls, implicit conversions and explicit casts, both locally and
through PCM. Direct, indirect, template and impl calls also check region writes.
Higher-ranked callable conversions use independent binder scopes and compose
shared covariance, mutable-content invariance and nested parameter contravariance.
Explicitly qualified packs preserve bindings, constraints, class projections and
return provenance during expansion. See
[SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md) for the admitted scope.

视图句柄的可变权限与其携带数据的权限分别检查：可以反复将同一份共享数据写回视图，
也可以在读取该数据时修改视图句柄。共享字段与独占字段混合时，各字段保留自身权限；
借用到句柄自身存储的引用、独占数据的冲突访问和短命数据写入仍被拒绝。来源无法恢复
的记录借用仍可能被保守拒绝。

A view handle's mutation permission is separate from its carried-data
permissions. Shared data may be written back repeatedly to the same view, and
the handle may change while that data is read. Mixed shared/exclusive fields
retain their individual permissions. Aliasing the handle's own storage,
conflicting access to exclusive data and shorter-lived writes remain rejected.
Record borrows whose storage cannot be recovered can still be conservatively
rejected.

组合测试区分复制出的视图和指向元素槽位的引用：源数据仍存活时，复制出的视图可以比
容器活得更久，但槽位引用不可以。测试还覆盖循环、分支、嵌套容器、所有权迁移、unsafe
返回契约和异常清理，并拒绝修改被共享视图借用的数据，以及多个容器保留的冲突独占借用，
其中也包括字段存储。

The composition checks distinguish a copied view from a reference to an
element slot. A copied view may survive the container when its source data
lives; a reference to the slot may not. They also test loops, branches,
nested containers, relocation, unsafe result contracts and exception cleanup.
They also reject mutation behind retained shared views and conflicting
exclusive borrows retained by separate containers, including field storage.

构造专项测试覆盖成员、基类、委托构造、模板和聚合初始化中的容器借用来源，
以及空容器、不同来源的独占借用和真实重叠借用。本地及跨 PCM 用例在 O0/O2 下运行，
正例使用 ASan/UBSan。具有显式类生命周期契约的构造函数体可以向成员容器写入，
包括循环和成员借用别名；局部数据逃逸、错误区域、成员尚未初始化和独占冲突会被拒绝。
这不代表任意构造函数体中的无契约来源推导均已支持。

Construction checks cover container borrow origins through member, base,
delegating, template and aggregate initialization, plus empty containers,
disjoint exclusive borrows and actual overlapping borrows. Local and cross-PCM
cases run at O0/O2, with ASan/UBSan for accepted programs. Constructor bodies
with explicit class lifetime contracts can populate member containers,
including through loops and borrowed member aliases. Escaping local data,
wrong regions, uninitialized members and exclusive conflicts are rejected.
This does not claim contract-free origin inference through arbitrary
constructor bodies.

非平凡析构可能延长容器保留借用的存活期：如果析构仍需要底层数据，应先结束容器的作用域，
再修改该数据。工厂测试覆盖本地及导入 PCM 的 API、直接及间接调用、空容器工厂、
所有权转发，以及对失效来源或伪造来源的拒绝。

Nontrivial destructors can keep a retained borrow live: end the container's
scope before modifying its backing data when the destructor still needs it.
The factory checks cover local and imported PCM APIs, direct and indirect
calls, empty factories, ownership forwarding, and rejection of expired or
invented sources.

替换测试覆盖整个所有者和嵌套字段：新值保留自己的借用来源，不会意外保留已经销毁的
源存储或已替换的依赖。析构检查包含自动析构、嵌套析构、异常清理及替换旧值时的析构。
外层容器仅执行 drop，并不意味着读取借用数据的元素析构函数可以免除生命周期检查。

Replacement checks cover whole owners and nested fields: the new value keeps
its borrow origins, while destroyed source storage and replaced dependencies
are not retained accidentally. Drop checks include automatic, nested,
exceptional and replacement destruction. A drop-only outer container does
not exempt an element destructor that reads the borrowed data.

线段树示例在 O0/O2、普通及 ASan/UBSan 配置下，每次运行执行 32,000 次随机操作，
并与普通数组模型对照。可执行文件和绑定到编译器版本的验证记录保存在 `build/segment-tree`。

The segment-tree example performs 32,000 randomized operations per run
against a plain-array model at O0/O2, plain and ASan/UBSan. Executables and
compiler-bound evidence are left under `build/segment-tree`.

## 支持边界 / Boundaries

类生命周期专项覆盖函数作用域的区域身份、可变类借用的区域约束、显式 outlives
关系、嵌套泛型字段投影及回调类型身份。本地和跨 PCM 的 O0/O2 配置均检查合法调用，
并拒绝短命来源写入、同名区域误匹配、错误字段区域和回调契约擦除；正例使用 ASan/UBSan。
这不代表完整高阶子类型与方差系统已经实现。PCM 格式已更新，旧 PCM 需要重新构建。

Class-lifetime checks cover function-scoped region identity, mutable class-borrow
region constraints, explicit outlives relations, nested generic field projections,
and callback type identity. Local and cross-PCM O0/O2 configurations check valid
calls and reject short-lived writes, accidental same-name region matches, wrong
field regions, and callback-contract erasure; accepted cases use ASan/UBSan.
This does not establish a complete higher-ranked subtyping and variance system.
The PCM format has changed; rebuild existing PCMs.

构造函数调用与普通函数调用共用实参生命周期检查：可变类区域约束和静态类区域约束
都必须满足，包括模板构造、抛异常构造及 unsafe 调用者。参数中的显式 `/static`
即使没有函数生命周期绑定列表，也必须保留在函数类型和 PCM 中。

Constructor and ordinary function calls share argument lifetime checks. Mutable
class-region and static class-region constraints apply to template constructors,
throwing constructors and unsafe callers as well. Explicit `/static` parameter
regions must survive function types and PCMs even without a function binder list.

来源永久有效的类视图可以通过函数／构造默认实参和默认成员初始化传递。
默认值仍按实际来源检查；显式覆盖成短命来源时会被拒绝。

Class views backed by permanent data can pass through function/constructor
default arguments and default member initializers. Defaults retain their actual
provenance; explicit shorter-lived overrides are rejected.

量化生命周期回调现在区分“类型相同”和“可以安全替换”。例如，接受两个独立共享
借用并返回第一个输入的函数，可以赋给要求两个输入共用较短区域的回调；反向转换
不能凭空承诺返回值只依赖第一个输入。参数中的嵌套回调反向检查，返回的回调正向检查。
可变类借用的内部区域、可变函数指针槽仍要求不变，不能通过转换产生短命写入能力。

Quantified-lifetime callbacks distinguish identical types from safe substitution.
For example, a function accepting two independent shared borrows and returning
the first may serve a callback requiring both inputs to share a shorter region.
The reverse cannot invent a promise that the result depends only on the first
input. Nested callback parameters are checked contravariantly and returned
callbacks covariantly. Embedded regions in mutable class borrows and mutable
function-pointer slots remain invariant, preventing conversions from introducing
short-lived writes.

重声明、虚覆盖和 impl 的契约身份规则不因此放宽。标准转换不能增加 safe／noexcept；
显式 unsafe 下原有的纯效果重解释仍由程序员负责，不代表子类型成立。经由 `void*`
擦除受检查的生命周期契约、改变不兼容返回来源，仍会报错。
任意外层区域捕获、完整泛型关联投影及生成式／static 返回互换尚未实现。
当前支持范围见架构文档，不能据此视为完整 Circle 兼容或生产安全认证。

Redeclarations, virtual overrides and impl retain exact contract identity.
Standard conversions cannot add safe/noexcept. Existing pure-effect
reinterpretations inside unsafe remain the programmer's responsibility and do
not establish subtyping. Erasing checked contracts through `void*` or changing
to an incompatible result source remains an error. Arbitrary outer-region
captures, complete generic associated projections and interchanging generative
and static results remain unsupported. See the architecture document for scope;
this does not establish complete Circle compatibility or production safety.

unsafe 代码仍是信任边界：调用者必须满足其契约，实现也必须兑现其承诺。
Sanitizer 测试成功只覆盖实际执行过的路径。

Unsafe code remains a trust boundary: callers must meet its contracts and its
implementation must actually uphold its promises. Successful sanitizer runs
only cover the executed paths.

完整的 interface/动态分派、任意类区域结构，以及所有间接借用元素契约，均不能视为已实现。
不支持的组合可能被拒绝。除非具体程序也与固定版本的 Circle 实现进行过对照，
否则本编译器接受该程序，并不能证明其行为与 Circle 一致。

Do not treat full interface/dynamic dispatch, arbitrary class-region shapes,
or every indirect borrowed-element contract as implemented. Unsupported
combinations may be rejected. Acceptance by this compiler is not evidence of
behavioral agreement with Circle unless the particular program has also been
compared with the pinned Circle implementation.
