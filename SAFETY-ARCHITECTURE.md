# 安全类型体系开发框架 / Safety Type-System Development Framework

本文件约束后续实现组织与验收，不是完成声明。目标仍是 Clang 22.1.2 上固定版本
Circle 的真实语法、类型和运行语义，优先保证 macOS arm64、O0 的原样官方安全库。
关闭扩展时保持上游 Clang 的语言和 ABI 行为。不能用保守拒绝替代最终完整兼容目标。

This document defines implementation boundaries and acceptance criteria, not a
completion claim. The target remains the pinned Circle syntax, types and runtime
semantics on Clang 22.1.2, prioritizing the unmodified official safety library on
macOS arm64 at O0. With extensions disabled, preserve upstream Clang language and
ABI behavior. Conservative rejection is an interim boundary, not a replacement
for eventual full compatibility.

## 依据 / References

参考版本由 `tools/circle_compatibility.py` 固定：Circle
`b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc`，Safe C++
`889685274438ca20344d4d9cb472e4392c4e35a9`。先核对本地参考代码和真实语义，
再修改规则。与参考实现对照、项目自身回归及 sanitizer 是三种不同证据，不互相替代。

`tools/circle_compatibility.py` pins Circle to
`b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc` and Safe C++ to
`889685274438ca20344d4d9cb472e4392c4e35a9`. Inspect the local reference sources and
actual semantics before changing rules. Reference comparisons, project regressions
and sanitizers provide distinct evidence; none substitutes for the others.

## 分层 / Layers

| 层 / Layer | 代码入口 / Code | 职责 / Responsibility |
| --- | --- | --- |
| 类型表示 / Representation | `clang/AST/TypeBase.h`, `Type.cpp`, `ASTContext.cpp` | 保存规范化绑定、类区域投影及关系；不依赖名字相同判断身份 / Store canonical bindings, projections and relations; spelling is not identity |
| 绑定与规范化 / Binding | `clang/lib/Sema/SemaType.cpp` | 作用域绑定、等价区域、传递闭包、静态约束及规范类型 / Bind scopes, equivalent regions, transitive closure, static constraints and canonical types |
| 关系查询 / Relations | `clang/AST/CircleClassLifetime.h`, `src/SafetyContracts.h` | 共用契约比较、区域查询和嵌套契约发现 / Shared contract comparison, region queries and nested-contract discovery |
| 语义入口 / Semantic entry points | `SemaDeclCXX.cpp`, `src/ModuleSafety.cpp` | 方法契约、转换及覆盖调用共享规则；保留各自额外效果要求 / Method contracts, conversions and overrides use shared rules plus their own effect requirements |
| 对象与控制流 / Objects and flow | `src/FlowAnalysis.cpp` | 将类型区域映射到实际来源，检查调用、写入、移动、析构和异常路径 / Map regions to actual origins; check calls, writes, moves, drops and exceptional paths |
| 持久化与执行 / Persistence and execution | `TypeProperties.td`, serialization, CodeGen | PCM、类型身份、符号及运行行为一致 / Preserve contracts through PCM, type identity, symbols and execution |

`clang/...` 路径相对于 `llvm-project-22.1.2.src`。原生修改必须进入补丁和源码清单；
共享检查器修改通过构建脚本同步。不要把第二个求解器写进某个 AST visitor。

`clang/...` paths are relative to `llvm-project-22.1.2.src`. Native changes must
enter the patch and source manifest; the build script synchronizes shared checker
sources. Do not introduce a second relation solver inside an AST visitor.

## 当前规则 / Current Rules

- 区域 ID 只在所属函数契约内有意义；未知区域不能当作任意区域或永久区域。
- 共享借用的生命周期缩短与可变位置写入不是同一规则；可变写入必须满足目标保存区域。
- 函数契约身份比较与调用点实参检查分开，不能用一种代替另一种。
- 存储来源与数据来源分别跟踪；每个来源的读写能力独立保存。可修改视图句柄不代表
  可以修改其只读数据，独占字段也不能获得共享字段的别名许可。
- 没有量化生命周期绑定不等于没有契约；静态类区域和返回来源必须独立保留。
- 来源必须区分参数携带的数据、按值参数自身的存储及其字段存储。数据满足 `static`
  或某个函数区域，不授权返回参数句柄或局部字段的地址。
- 显式 unsafe 允许已声明的底层操作，不允许调用者伪造受检查函数的生命周期契约。
- unsafe module 保持传统 Clang；不能声明 safe 函数。safe wrapper 的内部 unsafe
  不改变其对外分类，内部 lambda／函数体不继承 unsafe 权限。

- Region IDs are scoped to their function contract. Unknown does not mean
  arbitrary or permanent.
- Shortening shared borrows and writing mutable locations are different rules;
  writes must satisfy the destination's stored region.
- Contract identity and actual-argument checking are separate obligations.
- Track designated storage separately from carried data, with permissions per
  origin. A mutable view handle does not make its shared referents writable;
  exclusive fields do not gain the aliasing permission of shared fields.
- Absence of quantified bindings does not mean absence of contracts; preserve
  static class regions and return provenance independently.
- Distinguish carried parameter data from the storage of the by-value parameter
  and its fields. Static or quantified data regions do not authorize returning
  addresses of local parameter handles or fields.
- Explicit unsafe permits declared low-level operations, not forged lifetime
  contracts for checked functions.
- Unsafe modules retain traditional Clang behavior and cannot declare safe
  functions. Internal unsafe does not reclassify a safe wrapper; nested lambdas
  and function bodies do not inherit unsafe permission.

回调转换将契约身份与可替换性分开：重声明、覆盖和 impl 继续使用精确身份，
转换通过独立的方向性关系检查。现有实现仍不代表完整通用高阶子类型系统。
`circleSameFunctionLifetimeContract` 同时比较绑定、类区域投影、关系闭包、返回来源、
类返回区域及静态参数；`circleSameFunctionValueTypes` 比较参数、返回值及函数形状。
二者都不是完整安全效果比较器，safe 分类、调用约定及异常规范仍保留各入口的要求。

Callback conversions separate contract identity from substitutability:
redeclarations, overrides and impl keep exact identity, while conversions use
an independent directional relation. This does not establish a complete general
higher-ranked type system. `circleSameFunctionLifetimeContract` compares bindings, class
projections, relation closure, return sources, class-result regions and static
parameters. `circleSameFunctionValueTypes` compares parameter/result types and
function shape. Neither is a complete safety-effect comparator; entry points
retain their safety-classification, calling-convention and exception rules.

## 开发顺序 / Development Order

以下前四项已在 2026-10-27 按选定的 Circle 兼容扩展范围合并完成验收；当前实现、
运行语义边界及统一命令见 [FOUR-PILLARS.md](FOUR-PILLARS.md)。本次固定版本通过
前端 109/109、CTest 26/26、原样官方正例 14 文件／54 配置、默认 Clang 差分 13/13
及 103 文件无 fuzz 补丁重放，源码／二进制摘要一致，报告为
`build/four-pillars/acceptance.json`。后文各历史批次的局部通过及未完成描述保留其
当时语境，不替代本次四项合并验收。第五项完整语言兼容与跨平台发布仍是独立范围。

1. **区域关系闭环。** 集中现有查询和身份规则，再给重声明、覆盖、impl、转换、直接／间接
   调用建立同一组对照用例。已完成列出的原生入口统一，并通过下述统一矩阵与整批验收。
2. **通用高阶关系。** 在共享关系层实现独立绑定作用域、替换、共享协变和可变不变性，
   再支持嵌套函数参数的逆变组合。每次只放开有参考语义及正反例支撑的关系。
3. **泛型投影。** 统一显式类区域、类型参数携带区域和实例化后的字段映射；检查重复、
   重排、嵌套和静态区域，不用字段名称猜测来源。
4. **运行语义。** 分别验收自定义 relocation／locate、旧 C++ 按值 ABI、choice 组合、
   tuple 迭代与调用、slice 地址／长度 CodeGen 和 `~string` 类型解析。已有专项通过
   不自动意味着该类别全部完成。
5. **兼容与发布。** 建立完整 Circle 特性清单，逐项标明参考版本、实现入口、正反例、
   独立对照结果和缺口；以固定二进制验收，不能只汇总历史通过记录。

1. **Close the region-relation loop.** Centralize existing queries and identity
   rules, then exercise declarations, overrides, impl, casts and direct/indirect
   calls with corresponding cases. The listed native entry points are connected
   and have passed the common matrix and batch acceptance described below.
2. **General higher-ranked relations.** Implement independent binder scopes,
   substitution, shared covariance and mutable invariance in the shared relation
   layer, followed by contravariant nested-function parameters. Admit a relation
   only with reference semantics and positive/negative tests.
3. **Generic projections.** Unify explicit class regions, type-carried regions
   and instantiated field mappings, including repeated, reordered, nested and
   static regions. Do not infer provenance from field spelling.
4. **Runtime semantics.** Independently accept custom relocation/locate, legacy
   C++ by-value ABI, choice combinations, tuple iteration/calls, slice address/
   length CodeGen and `~string` type parsing. Existing targeted passes do not
   establish completion of an entire category.
5. **Compatibility and release.** Inventory all Circle features with reference
   version, implementation entry points, positive/negative cases, independent
   comparisons and gaps. Accept a fixed binary, not historical pass totals.

## 实现与回归节奏 / Implementation and Regression Cadence

按一组相关功能的语义闭环组织实现。先审查共享不变量、来源传播、控制流、模板替换和
跨模块入口，精细完成这一批实现，再统一构建和回归。不要把每个小修改都变成一轮全量
测试，也不要用反复运行已有绿灯测试替代代码推理。

开发期间只运行解决具体疑问所需的最小复现或针对性验证；遇到失败先分析共同根因和
同类入口，补齐实现后再验证。批次结束时固定二进制，集中执行相关专项、完整前端、
插件、Clang 差分和官方库验收。只有新增改动、失败或尚未解决的具体疑点才追加验证。
文档修改不触发编译器回归。

Implement batches of related features around a complete semantic path. Review
shared invariants, provenance propagation, control flow, template substitution
and module boundaries first; finish the batch carefully before a coordinated
build and regression run. Do not run the full suite after every small edit or
substitute repeated green test runs for reasoning about the code.

During implementation, use only the minimal reproducer or targeted check needed
to resolve a specific uncertainty. Analyze common causes and related entry points
before repairing and retesting a failure. At the batch boundary, freeze the binary
and coordinate relevant targeted checks, the full frontend suite, plugin tests,
Clang comparisons and official-library acceptance. Additional checks need a new
change, failure or unresolved concrete concern. Documentation edits do not trigger
compiler regressions.

## 验收 / Acceptance

2026-10-26，本批在修正后的固定二进制上通过：前端 98/98 项回归（其中包含
未经修改的官方正例 14 个文件、54 种配置）、插件 CTest 25/25、默认 Clang 有限差分
13/13，以及原始 LLVM 22.1.2 上 99 个文件的无 fuzz 补丁重放。统一矩阵的 100 项本地／
PCM 契约入口检查及 O0/O2 普通和 ASan/UBSan 运行均通过。能力矩阵另外通过 8 组运行
及 20 项本地／PCM 反例；官方 match／ref_cell 的来源退化已修复。以下支持边界仍然适用。

On 2026-10-26, the corrected fixed binary passed 98/98 frontend regression
checks, including 54 configurations across 14 unmodified official positive
test files; 25/25 plugin CTests; 13/13 bounded default-Clang differential cases;
and fuzz-free patch replay for all 99 files against pristine LLVM 22.1.2.
The common matrix passed 100 local/PCM contract-entry checks and O0/O2 plain
and ASan/UBSan execution. The capability matrix additionally passed eight
executions and 20 local/PCM refusals; official match/ref_cell provenance
regressions were repaired. The limitations below still apply.

### 入口矩阵 / Entry-Point Matrix

`tests/region_relation_entries.py` 将同一组规则用于重声明、虚函数覆盖、impl 契约、
隐式转换和显式转换，在本地与 PCM 两种入口分别检查。规则包括 alpha 等价、传递闭包、
等价区域合并、反向关系、关系擦除、返回来源改变、静态参数／返回值及类区域投影。
另检查导入类型身份、嵌套回调、函数指针存储层级和 unsafe 标记不能擦除契约。
直接、间接、模板及 impl 调用使用同一组可变区域正反例，unsafe 调用者也须满足契约。

`tests/region_relation_entries.py` applies the same rules to redeclarations,
virtual overrides, impl contracts, implicit conversions and explicit casts,
locally and through PCM. Rules include alpha equivalence, transitive closure,
equivalent-region merging, reversed/erased relations, changed return sources,
static parameters/results and class-region projections. Additional cases cover
imported type identity, nested callbacks, function-pointer storage layers and
unsafe annotations. Direct, indirect, template and impl calls share mutable-region
positive/negative cases; unsafe callers must satisfy the same contracts.

关联返回类型在替换后按唯一借用输入补全省略契约，再做完整比较，不能使用实现候选
声称的契约补全接口。矩阵同时覆盖关联视图返回、伪造静态返回及隐式虚析构函数。

After substitution, associated result types complete their elided contract from
the unique borrow input before full comparison; a candidate implementation's
claimed contract cannot supply the interface promise. The matrix also covers
associated view results, forged static results and implicit virtual destructors.

| 入口 / Entry | 共用规则 / Shared rule | 保留的入口要求 / Entry-specific requirements |
| --- | --- | --- |
| 重声明 / Redeclaration | `circleSameFunctionLifetimeContract` | 先完成契约省略／继承；保留合法重载 / Complete elision/inheritance first; preserve genuine overloads |
| 虚覆盖 / Override | 同上 / Same | 原生 Sema 发布前检查；保留 C++ 协变返回及异常规范规则 / Check before publishing from Sema; retain C++ covariant-return and exception rules |
| impl | 同上及 `circleSameFunctionValueTypes` / Same plus value-type equality | Self 替换、safe 效果、参数 ABI；允许更强 noexcept / Substitute Self; check effect/parameter ABI; allow stronger noexcept |
| 转换 / Conversion | `circleSameFunctionContractTree`、`circleFunctionTypeConvertible` | 精确身份与方向性替换分开；保留函数退化，禁止擦除存储层；标准转换不能凭空增加 safe／noexcept / Separate identity from substitutability; preserve decay/storage; standard conversions cannot invent safe/noexcept |
| 调用／返回来源 / Calls and result sources | `circleForEachFunctionRegionSource`、`circleFunctionRegionOutlives` | 从具体来源检查写入与存活；无法恢复来源则拒绝 / Check concrete origins for writes/liveness; reject unknown provenance |

这里的“闭环”针对规范契约身份与上述入口，不包含下一阶段的通用高阶子类型算法、
任意 unsafe 对象布局重解释或尚未支持的 Circle 语法。不得把这些用例的通过当成完整
Circle 兼容声明；本批验收必须包含固定二进制的全量前端与原样官方库回归。

This loop covers canonical contract identity at the listed entry points. It does
not include general higher-ranked subtyping, arbitrary unsafe object-layout
reinterpretation or unsupported Circle syntax. Passing this matrix does not
establish full Circle compatibility. Batch acceptance also requires the full
frontend and unmodified official-library regressions on the fixed binary.

### 通用高阶关系批次 / General Higher-Ranked Relations Batch

`CircleFunctionRelation.h` 集中实现方向性回调替换。每个函数原型比较创建独立作用域：
目标区域固定为占位节点，源区域使用新的推导节点；目标约束是已有假设，源约束与参数／
返回值转换产生待满足关系。对固定节点做传递闭包检查，禁止引入目标未承诺的区域关系，
包括把普通区域提升成 static。参数反向组合，返回值正向组合；嵌套回调重复这一过程。

`CircleFunctionRelation.h` implements directional callable substitution. Each
prototype comparison creates its own scope: target regions are rigid placeholder
nodes and source regions are fresh inference nodes. Target constraints are
assumptions; source constraints and parameter/result conversions add requirements.
Projecting the transitive closure onto rigid nodes may not invent a relation,
including promoting an ordinary region to static. Parameters compose
contravariantly and results covariantly, recursively for nested callbacks.

static 参数的固定身份同时应用于直接参数、where 边及类区域投影；混合的
`/(a,b where a: static,b:a)` 会保留这些关系。显式 static 返回只替换返回契约，
不能把原先省略的普通输入连带提升成 static。类型别名中显式写出的 unsafe 效果也
必须保留，不能被安全模块的默认分类覆盖。
static 要求同时沿 outlives 闭包传播：`b:a` 且 `a:static` 要求 `b` 的来源永久有效。
共享查询用于实参、类携带区域、函数体返回来源和 unsafe 函数的契约检查入口；空包
删除 static 参数后保留的 static 边也必须生效。数据永久有效不会延长局部视图句柄的存储期。

A static parameter's fixed identity applies to direct parameters, where-edges
and class projections. Mixed lists such as `/(a,b where a: static,b:a)` retain
these relations. An explicit static result replaces only the result contract;
it cannot promote an originally elided input to static. A function type alias's
written unsafe effect also survives the safe module's default classification.
Static requirements also propagate through the outlives closure: `b:a` with
`a:static` requires permanent origins for b. Arguments, carried class regions,
return provenance and unsafe-function contract discovery share this query,
including static edges retained after an empty pack removes their parameter.
Permanent data does not make a local view handle's storage permanent.

借用本身的持续期允许缩短；可变借用所指对象携带的区域要求不变。共享记录按字段映射
组合方差，并保守处理基类、未知映射及内部可变存储。共享接收者若暴露可变的区域承载
对象，也按不变处理。可变函数指针槽要求精确类型，不能因为槽内的函数值可转换就允许
改写槽。标准转换仍检查安全效果、异常规范、所有权参数位和 ABI；显式 unsafe 下原有的
纯效果重解释规则不作为子类型成立的证据。

Borrow durations may shorten; regions carried inside mutable referents remain
invariant. Shared records compose field variance, conservatively treating bases,
unknown mappings and interior mutable storage. A shared receiver exposing mutable
region-carrying objects also requires invariance. Mutable function-pointer slots
retain exact types even when their stored values can convert. Standard conversions
retain effect, exception, ownership-parameter and ABI checks. Existing pure-effect
reinterpretations inside unsafe do not establish a subtype relation.

运行时签名检查使用独立的契约擦除视图，递归处理回调，保留真实参数／返回类型、调用
约定和所有权 ABI。该视图只供 UBSan、CFI／KCFI 的签名标识使用，不修改语言类型身份、
名字修饰或运行时值。没有 Circle 契约的普通 Clang 类型保持原有标识处理。

Runtime signature checks use a separate contract-erased view, recursively through
callbacks, preserving value types, calling conventions and ownership ABI. Only
UBSan and CFI/KCFI signature identifiers use this view; language type identity,
symbol mangling and runtime values retain their existing behavior. Ordinary Clang
types without Circle contracts retain their existing identifier handling.

关系查询缓存本次已经成立的类型对，运行时签名视图按规范类型缓存重写结果，避免
重复嵌套同一回调类型时产生指数级工作。缓存不跨越编译上下文，也不缓存可能受递归
深度限制影响的失败关系。24 层重复参数／返回类型图作为本批复杂度回归。

Relation queries cache proven type pairs, while the runtime signature view caches
rewrites by canonical type, avoiding exponential work on repeated nested callback
types. Caches do not cross compilation contexts or retain relation failures that
may depend on a recursion-depth limit. A 24-level repeated parameter/result type
DAG is the complexity regression for this batch.

共享回调槽的结构查询、关系判定和运行时签名视图现在同时遍历原生借用 `T^`、
只读数组及成员函数指针；不会把 `T^` 当作普通 `T*` 擦除。嵌套参数继续反向组合，
返回值继续正向组合。可写回调槽、可写数组、成员数据指针及数组长度变化不能借此转换。
原生解引用和数组衰变只豁免编译器生成、且保留精确元素类型的投影；显式擦除仍检查契约。
直接成员数据指针转换与嵌套成员数据指针共用不变性规则。引用转换按表达式的值类别
补回存储层，不能把对可写函数指针槽的引用重解释成另一契约；只读槽和函数代码引用
仍保留有方向性证明的转换。

Contract discovery, scoped relations and runtime signature views traverse native
borrows `T^`, read-only arrays and member-function pointers. Native borrows keep
their representation rather than becoming raw pointers. Nested parameters compose
contravariantly and results covariantly. Writable callback slots, writable arrays,
member-data pointers and changed array bounds do not gain conversions. Only exact
compiler-generated dereference/array-decay projections bypass the cast barrier;
explicit contract erasure still requires the shared relation checks.
Direct member-data pointers use the same invariant storage rule as nested ones.
Reference casts recover their storage boundary from expression value categories,
preventing mutable callback slots from being retagged while retaining proven
conversions of read-only slots and immutable function-code references.

模板参数包替换记录每个展开参数的原始位置，并在重建原型前重写绑定、类区域投影、
outlives 边及返回来源。空包删除位置，多元素包复制对应位置；保留的区域按声明规则
重新规范化。显式限定的借用包按展开模式建立契约，类值与类借用包也保留携带区域。
专项覆盖 0、1、2、34 个前置普通参数与显式区域参数，包括超出 31 位来源位图的编码。
空来源包保留返回值的生成式契约，删除的区域不会留下幽灵约束；替换后的返回借用不能
逃逸局部存储。规范化前先取得可实例化的具体类定义，使相同签名不会因先前是否执行
`sizeof` 而获得不同契约；依赖模式不猜测尚未选定的类布局。

Template pack substitution records each expanded parameter's original position,
then rewrites bindings, class projections, outlives edges and return provenance
before rebuilding the prototype. Empty packs remove positions and multi-element
packs replicate them; retained regions are normalized in declaration order. Tests
cover 0, 1, 2 and 34 leading scalar or explicitly qualified parameters, including
borrow packs, record-value/record-borrow projections and expanded provenance beyond
the 31-bit source bitmap. Empty source packs retain generative result contracts;
removed regions leave no phantom constraints. Escaping local borrows are rejected
after substitution.
Normalization first completes available concrete class specializations, so a
signature's contract does not depend on whether an earlier `sizeof` instantiated
the class. Dependent patterns do not guess an unselected class layout.

数组字段先逐层取得元素，再组合其共享／可变借用、显式类区域和 `T+` 投影；数组长度
不生成新的区域。字段来源查询与方差查询使用同一元素区域映射。共享接收者暴露可写
数组指针时，包括数组别名，也检查其元素区域以保留内部可变性；只读数组结果保留
已证明的协变。`ClassVariance` 在单次关系查询内按记录及区域缓存成功证明，深度限制
导致的失败不进入缓存。

Array-field provenance and variance share the same element-region mapping, peeling
array ranks before composing borrow, explicit record-region and `T+` projections.
Bounds introduce no region. Shared receivers exposing writable arrays, including
through aliases, retain invariance for their element regions; read-only results
retain proven covariance. `ClassVariance` caches successful proofs by record and
region within a relation query; depth-limited failures are not cached.

参考语义来自固定的 Safe C++ 草案中区域约束与方差部分
（`downloads/safe-cpp-reference/proposal/draft.md:1564`、`:2784`），及
`topics.md:202` 对共享协变／可变不变性的讨论。后者是设计讨论，不是独立编译器
执行结果。每种放开的关系都配有正例与反向／存储修改／来源逃逸反例。

The pinned Safe C++ draft supplies the region-constraint and variance model
(`downloads/safe-cpp-reference/proposal/draft.md:1564`, `:2784`); `topics.md:202`
discusses shared covariance and mutable invariance. The latter is design discussion,
not an independent compiler execution result. Every enabled relation has positive
and reverse-direction, storage-mutation or provenance-escape negative cases.

补齐验证使用独立的有限生命周期集合模型：枚举 16 种原型的合法区域赋值，用“每个目标
调用都存在一个可用的源绑定”计算替换关系，得到 127 对正例和 129 对反例，再组合参数、
返回值、多层逆变、只读槽、数组、成员函数指针及兄弟作用域。本地与 PCM 共执行
6,144 条断言；预期关系不调用编译器的图闭包算法。参数包专项另有 106 条类型身份断言、
79 次编译与 8 次 O0/O2 普通及 ASan/UBSan 执行，包括普通类型参数和 `T+`、实例化顺序、
空包、static 约束、34 个来源及局部逃逸拒绝。

Completion verification uses an independent finite live-point-set model. It
enumerates legal assignments for 16 prototypes and asks whether every target
call admits a source instantiation, yielding 127 accepted and 129 rejected base
pairs. Argument/result composition, repeated contravariance, read-only slots,
arrays, member-function pointers and sibling scopes produce 6,144 local/PCM
assertions. Expected relations do not call the compiler's graph-closure solver.
Qualified-pack tests add 106 type-identity assertions, 79 compilations and eight
O0/O2 plain and ASan/UBSan executions, covering ordinary type parameters and T+,
instantiation order, empty packs, static constraints, 34 sources and local escapes.

本批仍不包括捕获外层区域的任意嵌套绑定、完整类类型参数方差、所有泛型关联投影、
完整数组别名区域投影、此前不支持的类值数组构造，或生成式返回与 static 返回的互换。
未知来源、未知布局和未表示的区域不能借转换绕过。

This batch excludes arbitrary nested binders capturing outer regions, complete
class type-parameter variance, all associated projections, complete array-alias
region projection, previously unsupported record-array construction, and
interchanging generative and static results. Unknown provenance, layouts and
unrepresented regions cannot bypass checks.

2026-10-26，本批首次固定二进制通过前端 **100/100**、插件 CTest **25/25**，
其中原样官方正例为 **14 个文件、54/54 种配置**。高阶关系专项覆盖 **586** 项本地／
PCM 隐式、显式及模板转换，另有引用槽／成员数据槽／借用逃逸拒绝；数组区域专项覆盖
**150** 项转换。两组各有 8 组 O0/O2 普通及 ASan/UBSan 执行，并覆盖 24 层重复类型图。
真实 ABI 不匹配的 UBSan 拒绝、CFI/KCFI IR 标识、默认 Clang 有限差分 **13/13** 及
**100 文件**无 fuzz 补丁重放全部通过。未执行独立 Circle 二进制对照。

The first accepted binary passed **100/100** frontend regressions and **25/25** plugin
CTests on 2026-10-26, including **54/54** configurations across **14** unmodified
official positive files. The higher-ranked suite covers **586** local/PCM implicit,
explicit and template conversions plus storage/provenance refusals; array regions
cover **150** conversions. Each suite runs eight O0/O2 plain and ASan/UBSan programs
and tests 24-level repeated type DAGs. Real ABI-mismatch UBSan rejection, CFI/KCFI
IR identifiers, **13/13** bounded default-Clang comparisons and fuzz-free replay of
**100** patched files passed. No independent Circle binary comparison was performed.

完整日志、源码／驱动／前端动态库／插件摘要及边界记录于
`build/higher-relations-acceptance.json`。先前的 99/99 与中止执行属于历史记录，
不计作本次验收；本次验收期间源码和二进制摘要未漂移。

Logs, source/driver/frontend-library/plugin digests and limitations are recorded in
`build/higher-relations-acceptance.json`. Earlier 99/99 and interrupted runs are
historical records, not this acceptance; the accepted source/binary snapshot did
not drift during verification.

2026-10-27，补齐显式参数包、具体类实例化顺序及隐含 static 要求后的固定版本通过
前端 **104/104**、插件 CTest **26/26**、原样官方正例 **14 文件／54 配置**、默认
Clang 有限差分 **13/13** 和 **100 文件**无 fuzz 补丁重放。上述 6,144 条独立模型断言、
106 条参数包类型身份断言及原有高阶／数组／运行时签名专项均在该版本通过；验收期间
源码和二进制摘要无漂移。完整记录为 `build/higher-relations-complete/acceptance.json`，
其中中间版本记录明确排除在最终验收之外。

The completed version passed **104/104** frontend regressions, **26/26** plugin
CTests, **54** configurations over **14** unmodified official positive files,
**13/13** bounded default-Clang comparisons and fuzz-free replay of **100** files
on 2026-10-27. The 6,144 independent-model assertions, 106 qualified-pack type
identities and existing callable/array/runtime-signature suites passed on this
version without source or binary drift. Final evidence is recorded in
`build/higher-relations-complete/acceptance.json`; intermediate versions are
explicitly excluded from that acceptance.

### Circle 兼容捕获与泛型关系扩展（2026-10-27）

本批按选定的 **Circle 兼容扩展**定义语义，沿用 `/()`、`where`、`T+`、
类区域实参及 C++ 关联类型语法。固定 Safe C++ 草案在 `proposal/draft.md:1884`
明确只描述当前函数的规范化区域参数；以下跨作用域捕获是本仓库明确规定的扩展，
不能冒称已由官方 Circle 二进制确认。没有引入 Rust 的 trait、HRTB 或 GAT 语法。

- **词法绑定与替换。** 捕获身份由绑定层距和绑定槽组成，不使用变量拼写作为身份。
  内层同名参数遮蔽外层参数；每个函数原型（包括没有显式绑定列表的原型）占据独立
  作用域。嵌套输入、输出及 outlives 约束均可引用外层绑定；声明规范化和参数包替换
  统一重建捕获映射。删除空包后仍被回调使用的绑定保留，重新编号后排序的捕获角色
  也同步重建。显式类区域可用于其回调字段。
- **量词与关系。** 每层比较验证 `∀目标区域. 目标约束 ⇒ ∃来源区域.
  (来源约束 ∧ 函数关系)`；返回位置协变，函数参数位置反转。捕获保持自由，直到其
  所属外层原型关闭作用域；外层的存在选择不能依赖之后的内层全称选择。兄弟原型
  的约束不互相提供假设。区域集合按成员关系逐点表示，使用约简决策图消去量词；
  节点预算耗尽时拒绝关系。原有闭合 generative 与 static 契约仍不能互换，原始指针
  generative 来源也不因捕获关系而被擦除。
- **类参数方差。** `T+` 将函数类型实参的自由区域提升到类的区域槽，规范化名义类型
  中保存形式槽，使用处的 `/a`、`/b` 保存实际区域。共享类字段按双变、协变、逆变、
  不变四点格组合；回调的区域方向来自同一量化关系。固定点遍历记录类型图，重复
  字段和共享子图不反复展开。可变字段、可写载荷和暴露可写区域存储的共享方法保持
  不变；没有可证明字段映射或完整表示的类按不变处理，不能因此放宽转换。普通 C++
  名义类型和其他模板实参的类型身份要求继续保留。
- **泛型关联投影。** 去糖前保留模板参数声明身份、参数包元素及限定名的替换环境。
  支持关联别名链、嵌套模板、偏特化、继承的关联别名、成员别名模板和包索引元函数。
  偏特化先将推导参数映射回主模板区域跨度，再组合字段投影；相同实际类型也不能
  合并不同参数的身份。查询按类型与完整替换环境记忆化，不再以旧的 16/32 层阈值
  截断有效投影。存在歧义、递归环或无法恢复的关联映射时仍是未知，不能提供借用
  安全证明。此处的“关联投影”是现有 C++/Circle 关联类型，非 Rust trait GAT 系统。
- **值来源。** 捕获型回调的每个自由区域分别保存来源，覆盖参数、局部值、返回值、
  类字段、复制、重新绑定和 CFG 合流；未知分支污染合流。双区域回调的类返回、
  聚合初始化和临时返回值成员调用分别保留输入／输出角色；合并字段贷款保留所有
  捕获区域的活性，调用查询使用逐角色来源。调用时分别验证捕获输入
  与返回来源，移动、字段退役和作用域结束同步退休摘要。闭合多态代码可以实例化为
  捕获型回调，不要求两者自由区域数量相等。代码能力不冒充一次数据读取；实际返回
  的 static 数据继续接受普通全局副作用检查。运行时仍使用原有函数指针 ABI。

`tests/outer_region_captures.py` 用独立枚举的区域集合模型验证 **2,768** 条引用／值借用模式的本地／PCM
关系断言，并检查空包后的捕获身份；`tests/class_parameter_variance.py` 验证四类方差、
高阶组合和 48 层共享类型图的 **132** 条本地／PCM 断言。
`tests/captured_callable_values.py` 覆盖 **69** 次编译及 **8** 次 O0/O2、普通和
ASan/UBSan 运行；`tests/generic_region_projection.py` 扩展到 **396** 项检查及
**8** 次同类运行。它们和原有 6,144 条独立绑定集合模型均纳入完整前端门禁。

参考语义：固定 Safe C++ 草案的区域约束、模板生命周期提升及字段方差；
[Rust Reference：子类型与方差](https://doc.rust-lang.org/reference/subtyping.html)、
[rustc：高阶区域量化](https://rustc-dev-guide.rust-lang.org/traits/hrtb.html)、
[rustc：方差固定点](https://rustc-dev-guide.rust-lang.org/variance.html)提供对照。
这些资料支撑规则设计，不证明本实现与其他编译器完全等价。完整回归、补丁重放和
固定摘要的本批结果记录于 `build/complete-region-system/acceptance.json`。

### 泛型区域投影批次 / Generic Region Projection Batch

`CircleClassRegionProjection` 按模板参数声明身份计算字段的区域映射，而不按字段顺序
累加。`Reorder<A+,B+>{B first;A second;}` 的两个字段即使实例化成相同类型，仍分别
对应 B、A；重复使用同一参数则重复原映射，不额外发明区域。映射位于共享 AST 层，
来源初始化、参数与返回值检查、嵌套路径组合及类区域方差查询共用它。

`CircleClassRegionProjection` maps fields by template-parameter identity, rather
than accumulating field order. In `Reorder<A+,B+>{B first;A second;}`, equal actual
types still retain distinct B/A origins. Repeated parameter uses repeat the same
mapping without inventing regions. Shared AST helpers serve provenance setup,
argument/result checking, nested paths and class-region variance.

映射在去糖前读取替换类型，保留模板参数身份和参数包元素位置。别名和嵌套容器逐层
组合；偏特化先投影特化模式与主模板的对应关系，再映射实际字段。规范化的偏特化
参数使用其语义深度／索引；不能唯一恢复的映射保留未知并拒绝需要该证明的操作。
显式特化仅在实际参数能唯一确定区域跨度时恢复已有投影。

The mapper reads substitution sugar before desugaring, retaining parameter and
pack-element identities. Aliases and nested containers compose recursively.
Partial specializations project their pattern onto primary-template regions before
mapping fields; canonical pattern parameters use semantic depth/index identities.
Ambiguous mappings stay unknown and cannot justify a checked operation. Explicit
specializations retain projections only where actual arguments identify a unique
region span.

数组别名按元素计数区域，未声明 `T+` 的参数包不生成模板区域。读取已知数组中的
借用值使用数组保存的载荷来源，而不是数组中借用句柄的存储地址；因此按值参数内的
数组可以返回其所携带的合法借用，但不能使本地承载对象变成永久对象。
static 区域和普通区域混合时逐项保留；static 载荷不能替承载它的参数存储提供永久性。

Array aliases count element regions; unmarked template packs invent no template
regions. Reading borrow-valued elements of a known array uses saved payload
provenance, rather than the address of handle storage. Arrays in by-value parameters
can return valid carried borrows without making local carriers permanent. Mixed
static/ordinary regions remain distinct; permanent payloads do not make parameter
storage permanent.

参考为固定 Safe C++ 草案 `proposal/draft.md:1790–1859` 的模板生命周期参数与
hoisting 规则，以及 `:1551–1603` 的区域约束；未执行独立 Circle 二进制对照。
专项 `tests/generic_region_projection.py` 覆盖重复、重排、嵌套、别名、参数包、偏／显式
特化、混合 static、不同区域的不同方差及来源逃逸；验证本地和 PCM 下 O0/O2 普通与
ASan/UBSan 运行。完整门禁结果与固定摘要记录于 `build/generic-projections-acceptance.json`。

References are the pinned Safe C++ draft's template-lifetime/hoisting rules
(`proposal/draft.md:1790–1859`) and region constraints (`:1551–1603`). No independent
Circle binary comparison was performed. `tests/generic_region_projection.py`
covers repetition, reordering, nesting, aliases, packs, partial/explicit
specializations, mixed static regions, per-region variance and escaping sources,
including local/PCM O0/O2 plain and ASan/UBSan runs. Full gates and fixed digests
are recorded in `build/generic-projections-acceptance.json`.

2026-10-26，本批固定二进制通过 **236** 项本地／PCM 专项检查、**8** 次运行验证、
前端 **101/101**、CTest **25/25**、原样官方正例 **14 文件／54 配置**、默认 Clang
有限差分 **13/13** 和 **100 文件**无 fuzz 补丁重放；验收期间摘要无漂移。
额外 25 层嵌套构造探针超过 30 秒预算，没有得到接受／拒绝结论；深嵌套性能仍是
待办，不能把有界专项通过扩展为任意深度的可用性声明。

The fixed binary passed **236** local/PCM checks, **8** runtime executions,
**101/101** frontend regressions, **25/25** CTests, **54** configurations across
**14** unmodified official positive files, **13/13** finite default-Clang
differentials and a no-fuzz **100-file** patch replay on 2026-10-26. Acceptance
digests did not drift. An additional 25-level nested-construction probe exceeded
its 30-second budget without an accept/reject result. Deep-nesting performance
remains open; these bounded checks do not establish arbitrary-depth availability.

上述超时属于当时固定二进制的结果；下面的初始化图批次已解决该探针的超时。
另一个独立缺口仍保留：25 层 `T+` 链显式写出 `/a` 时，既有有界区域计数会报告
`expected 0, got 1`。局部借用值的深嵌套检查通过不代表深层显式区域投影已经完成。

The timeout above describes that historical binary; the initializer-graph batch
below resolves it. A separate gap remains: explicitly writing `/a` on a 25-level
`T+` chain reaches the existing bounded region count and reports `expected 0,
got 1`. Deep local-borrow checks do not establish deep explicit-region projection.

### 初始化图遍历与来源求解 / Initializer Graph Traversal and Provenance

采样确认三个独立的重复计算来源：声明分类器对初始化列表的语法／语义两种形式反复
遍历共享子树；聚合来源查询在临时借用检查和载荷检查中重复递归；CFG 查询父节点时
构建整个翻译单元的父关系，连未实例化的深层初始化图也反复访问。

Sampling identified three independent sources of repeated work: classification
traversed shared children of syntactic/semantic initializer forms repeatedly;
aggregate provenance recursed separately for temporary-borrow and payload checks;
CFG ancestry queries built a whole-TU parent map including uninstantiated deep
initializer graphs.

`src/SafetyTraversal.h` 提供两种共享设施。`InitListVisitSet` 保留两种形式的回调，
每个检查上下文只遍历同一对列表一次；主检查器区分函数、checked／unsafe、依赖体、
unsafe 初始化、受信任内存操作和拥有构造模式，构造成员读取检查还区分初始化阶段。
`AnalysisParents` 仅索引当前被分析函数内 CFG 所需的语句／声明祖先，每次先记录
传入父边，再决定是否复用已遍历的子树；共享节点的多个父节点不能被合并成第一个。
它不替换上游 Clang 的全局父关系 API，也不提供 TypeLoc／属性祖先查询。

`src/SafetyTraversal.h` shares two facilities. `InitListVisitSet` preserves both
forms' callbacks while traversing each pair once per checking context. The main
checker distinguishes functions, checked/unsafe mode, dependent bodies, unsafe
initializers, trusted memory operations and owned-construction modes; constructor
member-read checks also distinguish initialization phases. `AnalysisParents`
indexes only the current function's statement/declaration ancestry needed by its
CFG. It records every incoming edge before reusing a traversed subtree, retaining
all parents of shared nodes. It neither replaces upstream Clang's global parent
API nor supplies TypeLoc/attribute ancestry queries.

聚合初始化中的来源只在同一次查询、同一不可变 `State` 内复用，不使用跨写入或跨
控制流状态的缓存。兄弟实参求值副作用、独占别名和未知全局写入仍使用原有规则。
新增共享头进入原生／插件的构建依赖、源码复制和检查器指纹，并更新伪造指纹反例。

Aggregate initializer roots are reused only within one query in the same immutable
`State`, without caching across writes or CFG states. Sibling-evaluation effects,
exclusive aliases and unknown global writes retain their checks. Both builds,
source copying and checker fingerprints include the new shared header; counterfeit
fingerprint regressions compute the updated identity.

专项 `tests/initializer_traversal.py` 对原生和出树插件分别执行 51 次本地／PCM 编译、
8 次 O0/O2 普通及 ASan/UBSan 运行，包含 25／40 层值与借用、局部来源逃逸、共享／
独占别名、兄弟副作用、隐式数组填充、默认初始化异常及模板／unsafe 上下文。
原 25 层超时探针现已快速诊断为非法逃逸；性能数字只描述本机固定二进制及所测输入。
门禁、源码／二进制摘要和性能记录见 `build/initializer-traversal-acceptance.json`。

`tests/initializer_traversal.py` exercises native and out-of-tree-plugin builds
with 51 local/PCM compilations and eight O0/O2 plain/ASan/UBSan executions each:
25/40-level values and borrows, escaping local origins, shared/exclusive aliases,
sibling effects, implicit fillers, default-initialization exceptions and independent
template/unsafe contexts. The original 25-level timeout probe now quickly diagnoses
an invalid escape. Timing evidence describes this machine, binary and tested inputs.
Gates, source/binary digests and measurements are recorded in
`build/initializer-traversal-acceptance.json`.

2026-10-26，本批固定二进制通过前端 **102/102**、CTest **26/26**（包含新增插件
初始化图专项）、官方原样正例 **14 文件／54 配置**、默认 Clang 有限差分 **13/13**
与 **100 文件**无 fuzz 补丁重放。验收期间源码／二进制摘要无漂移；原 25 层非法
逃逸探针在并行门禁期间耗时约 **0.11 秒**。这些结果不覆盖上述深层显式区域计数缺口，
也未提供独立 Circle 二进制对照。

The fixed binary passed **102/102** frontend regressions, **26/26** CTests
(including the new plugin initializer-graph test), **54** configurations across
**14** unmodified official positive files, **13/13** finite default-Clang
differentials and a no-fuzz **100-file** patch replay on 2026-10-26. Source/binary
digests did not drift. The original 25-level invalid-escape probe took about
**0.11 seconds** during parallel acceptance. This does not close the deep explicit
region-count gap above or provide an independent Circle binary comparison.

`State::BorrowStorage` 保存借用／引用实际指向的存储，绑定和重绑定时更新；分支合并
要求两侧来源均已知，再合并可能的存储。它不替代存活、移动、析构及区域契约检查。
`Loan::WriteRoots` 保存每个来源的写入能力，未建模时保留原有保守权限。字段、聚合
及分支合并均保留这一区分；普通调用、构造调用、隐式接收者和参数求值共用能力查询。

`State::BorrowStorage` records storage designated by a borrow/reference and is
updated on binding and rebinding. Joins combine possible storage only when both
inputs are known. It does not replace liveness, move, drop or region-contract
checks. `Loan::WriteRoots` records write permission per origin, falling back to
the existing conservative permission when unmodeled. Fields, aggregates and
joins preserve this distinction; ordinary/constructor calls, implicit receivers
and argument evaluation share the capability query.

读取借用字段也读取字段句柄本身的存储，因此容器的存活独占别名仍禁止直接读取该字段；
通过句柄修改所指数据不等于修改句柄存储。能力查询沿用声明绑定的匹配来源规范化，
不能把已经结束的 match 临时绑定重新加入返回借用的来源。

Reading a borrow field also reads its handle storage, so a live exclusive alias
of the holder still forbids direct field reads. Writing the referent through a
handle does not write the handle slot. Capability queries use the same match
provenance normalization as declaration binding; ended match temporaries must
not be reintroduced as owners of a returned borrow.

区域入口运行矩阵已恢复同一容器反复写回已关联数据的场景。
`tests/borrow_capabilities.py` 另外覆盖存活的共享别名、可变别名、重绑定、分支、循环、
共享／独占字段混合及兄弟参数求值，并拒绝真实存储重叠、独占数据重叠、短命写入及
构造调用破坏临时借用。存储未知、携带数据和存储无法区分、部分存储在字段中的记录
借用等情形仍保守处理；重叠的 union／choice 活动载荷继续使用原有投影检查，不能
套用普通记录的存储细分。这不是完整高阶子类型或任意布局分析。

The region-entry runtime matrix again writes previously associated data back to
the same holder. `tests/borrow_capabilities.py` additionally covers live shared
aliases, mutable aliases, rebinding, branches, loops, mixed shared/exclusive
fields and sibling-argument evaluation. It rejects actual storage overlap,
exclusive-data overlap, short-lived writes and constructor calls invalidating
temporary borrows. Unknown storage, indistinguishable storage/data sources and
some record borrows stored in fields remain conservative. Overlapping union and
choice payloads retain their existing projection checks rather than ordinary
record storage refinement. This does not establish general higher-ranked
subtyping or arbitrary object-layout analysis.

`tests/class_lifetime_variance.py` 为下列交叉组合提供专项正反例。
这些是已命名的测试覆盖，不是整个入口或类型系统的完成声明。

`tests/class_lifetime_variance.py` supplies targeted positive/negative cases for
the combinations below. These name test coverage, not completion of an entire
entry point or type system.

| 规则 / Rule | 入口 / Entry points | 必须保持的行为 / Required behavior |
| --- | --- | --- |
| 可变类区域 / Mutable class region | 普通、间接、构造、模板构造、抛异常构造 / Ordinary, indirect, constructor, template constructor, throwing constructor | 短命来源不可写入长命区域，unsafe 调用者也须满足契约 / Reject shorter-lived writes, including unsafe callers |
| 静态类区域 / Static class region | 普通、间接、构造；显式绑定列表及省略列表 / Ordinary, indirect, constructor; explicit and omitted binder lists | 检查保存的数据区域，而非要求承载视图的局部变量永久存活 / Check backing-data regions, not permanent storage for the local view handle |
| 量化契约 / Quantified contract | 转换、别名、嵌套回调、函数引用 / Casts, aliases, nested callbacks, function references | 不可擦除或伪造，等价契约保留可用性 / Reject erasure/invention, retain equivalent contracts |
| 规范区域关系 / Canonical relation | 类型身份、直接及间接调用 / Type identity, direct and indirect calls | 传递关系与等价直接关系一致；反向关系不授权写入 / Transitive and equivalent direct constraints agree; reversed constraints do not permit writes |
| 依赖投影 / Dependent projection | `T+` 模板声明、实例化、本地及 PCM 消费者 / T+ declarations, substitution, local and PCM consumers | 未替换时保留区域图，替换后检查数量及具体字段；模块安全消费者保留原生类型投影 / Preserve the graph before substitution; check concrete arity/fields afterward; retain native projections in module-only consumers |
| 存储身份 / Storage identity | 普通及静态返回、别名、模板实例化、本地及 PCM / Ordinary/static returns, aliases, substitution, local and PCM | 局部句柄和字段可在函数内部借用，但不可作为外部参数区域或永久区域返回 / Permit local handle/field borrows within the function; reject returning them as external or permanent regions |

构造和普通调用通过 `src/FlowAnalysis.cpp` 中的 `Analysis::argumentLifetimeContracts` 共用静态参数与类区域
检查。以后新增调用形式时，必须明确接入此入口，或提供其不需要该检查的理由及测试。

Constructors and ordinary calls share static-parameter and class-region checks
through `Analysis::argumentLifetimeContracts` in `src/FlowAnalysis.cpp`. New invocation forms must
connect to this entry point or document and test why it is not applicable.

默认实参和默认成员初始化包装必须向字段来源提取器传递实际表达式，不能因包装而丢掉
区域，也不能因使用默认值而假定永久有效。专项包含函数／构造默认值、显式临时值、
嵌套字段默认初始化及短命来源覆盖。字段保存的数据来源与临时对象的存储寿命分别检查；
提取字段来源不延长对象存活期。

Default-argument and default-member-initializer wrappers must expose their actual
expressions to field-provenance extraction, without losing regions or assuming
permanence. Targeted cases include function/constructor defaults, explicit
temporaries, nested field defaults and shorter-lived overrides. Carried-data
provenance and temporary storage lifetime are checked separately; extracting
field provenance does not extend an object's lifetime.

`tests/multi_region_class_values.py` 覆盖标量借用参数构造多区域返回值时的直接及传递
生命周期缩短。函数体返回检查和调用方字段来源摘要必须查询同一规范区域关系；摘要合并
全部允许的来源，不能只选首个匹配参数。反向关系、字段交换和活跃借用期间的写入仍拒绝。
多区域类按值转发现在按参数的各区域投影恢复字段来源，不依赖函数与类声明的名字相同。
专项覆盖直接／间接调用、区域重排、缩短、嵌套及函数模板转发；移动句柄不使已转移的
字段来源失效，但重复移动仍拒绝。这不表示通用高阶子类型已经完成；本组未执行独立
Circle 二进制对照。

类参数返回单个借用时，也必须匹配具体来源区域，不能只匹配参数身份。
直接和间接调用共用 `argumentResultRoots`，只传播满足结果区域约束的参数投影；
否则既可能接受错误字段，也可能把独立区域错误地保持借用。

`tests/multi_region_class_values.py` covers direct and transitive shortening from
scalar borrow parameters into multi-region results. Return checking and call-site
field summaries query the same canonical relation; summaries union all eligible
sources rather than selecting the first match. Reversed relations, swapped fields
and writes during live borrows remain rejected. Multi-region class-value forwarding
recovers field provenance from parameter-region projections, independent of binder
spelling. Cases cover direct/indirect calls, remapping, shortening, nested fields
and function templates. Moving a handle transfers its field loans; repeated moves
remain rejected. General higher-ranked subtyping remains incomplete. These cases
have not been independently compared against a Circle binary.

A single borrow returned from a class parameter must match the specific
source region, not merely the parameter's identity. Direct and indirect calls
share `argumentResultRoots`, propagating only parameter projections that satisfy
the result-region constraint. Otherwise wrong fields may be accepted and
independent regions may be unnecessarily kept borrowed.

类参数的携带区域与其自身借用区域分别参与返回来源查询。比如
`const Pair/a/b^/call` 的 `/a`、`/b` 不等于 `/call`：返回数据可依赖前两者，
返回对象物理字段的地址则依赖后者。`argumentRegionRoots` 同时供单借用返回及多字段
返回使用；一个获准来源无法恢复时，不能只保留其他来源并继续接受。
混合静态结果保留每个区域的投影，例如 `Pair/static/b`；只有全部区域永久有效才使用
整体静态结果契约。`tests/borrowed_class_results.py` 覆盖直接／间接访问、共享借用参数、
T+ 模板、区域重排及缩短、混合静态结果和载体结束后数据仍存活的情形。诊断反例不随
优化级别重复，运行正例覆盖本地与 PCM、O0/O2 及 ASan/UBSan。
模块安全消费者向导入的原生借用参数传参时，以目标类型决定句柄表示，不能因当前
默认采用引用借用而改变 PCM 的 ABI。延迟实例化产生的隐式平凡构造／析构使用与声明
分类相同的规则；可变借用复制、显式 unsafe 子对象操作和不安全模块仍不获得自动授权。
类区域查询穿过清理、临时对象、同类型构造转换及隐式复制／移动包装，单区域间接容器从已保存的数据
摘要恢复来源。没有显式携带区域投影的传统接收者仍按返回契约区分存储借用与数据复制，
不能一律改成依赖接收者存储；多区域容器不能套用单区域汇总。

Carried regions and the class parameter's own borrow region participate separately
in result provenance. In `const Pair/a/b^/call`, `/a` and `/b` are distinct from
`/call`: returned data may depend on the former, while addresses of physical
carrier fields depend on the latter. `argumentRegionRoots` serves both scalar
borrow and multi-field results. If an eligible source cannot be recovered, it
must not be silently dropped while other sources are retained. Mixed static
results preserve every projection, as in `Pair/static/b`; only entirely permanent
results use the whole-result static contract. `tests/borrowed_class_results.py`
covers direct/indirect access, shared borrowed parameters, T+ templates, remapping,
shortening, mixed static results and data that survives its carrier. Diagnostic
negatives are not repeated by optimization level; runtime positives cover local
and PCM use, O0/O2 and ASan/UBSan.
In module-only consumers, an imported native borrow destination determines the
handle representation, independent of the current reference-borrow default.
Lazy implicit trivial construction/drop uses the same inference as declaration
classification; exclusive-borrow copying, explicit unsafe subobject operations
and unsafe modules receive no additional authorization.
Class-region queries unwrap cleanups, temporaries, same-type constructor casts and implicit copy/move nodes;
single-region indirect containers recover their saved data summary. Conventional
receivers without explicit carried-region projections still distinguish storage
borrows from payload copies through their result contracts. A single-region
aggregate summary cannot stand in for individual regions of a multi-region container.

`tests/nested_class_values.py` 覆盖 `Wrapper<T>/x/y` 在 `T+` 替换后的多区域转发与
单区域提取。依赖的区域数量在实例化时检查；显式声明的固定数量仍在声明处检查。
依赖来源类型的借用形状也必须在实例化后重新验证，不能在模板模式中猜成不含借用。
带原生生命周期元数据的 PCM 类型保留逐字段投影，不因消费者未开启借用值语法而合并
来源。静态嵌套结果只将借用叶子的来源标记为永久，不延长返回对象自身的存储寿命。
本组未执行独立 Circle 二进制对照。借用字段中再嵌入带生命周期类的可写引用仍有
投影缺口；已审核的组合被拒绝，不能据此声称这一类互操作完成。

`tests/nested_class_values.py` covers multi-region forwarding and single-region
extraction after substituting T+ in `Wrapper<T>/x/y`. Dependent arity is checked
at instantiation; explicitly declared fixed arity is checked at declaration.
Borrow-carrying source shapes are also rechecked after substitution, rather than
assuming a dependent carrier contains no borrows. PCM types with native lifetime
metadata retain per-field projections in module-only consumers. Nested static
results make only carried borrow origins permanent, not the result object's
storage. These cases have not been independently compared against a Circle
binary. Mutable borrowed fields referring to lifetime-bearing records still have
projection gaps; the audited combinations are rejected, not completed interop.

`FlowAnalysis.cpp` 的 `OriginOwners` 记录字段与所有者的别名关系；
`ParameterRegions` 记录调用者提供的来源，不得用它给按值参数的物理字段授予外部区域。
通过引用或借用接收者访问的字段仍属于接收者指向的对象。借用参数的局部句柄使用独立
存储身份，随参数一起结束；取句柄地址不能复用其指向数据的区域。
取地址的来源通过 `addressStorageRoots` 独立查询，并沿逗号、条件和赋值表达式传播；
接收者的数据访问不能混入局部句柄的存储。原样 `rc_test` 验证接收者返回数据仍可用。
`tests/static_results.py` 检查普通／unsafe 函数及静态约束下的句柄返回；
`tests/nested_class_values.py` 检查按值字段的普通／静态返回、别名、模板和 PCM，
并运行合法的函数内局部借用。

In `FlowAnalysis.cpp`, `OriginOwners` records field/owner alias relationships;
`ParameterRegions` records caller-supplied origins and must not grant an external
region to physical fields of by-value parameters. Fields reached through reference
or borrow receivers still belong to the referred object. A borrow parameter's
local handle has a distinct storage identity that ends with the parameter;
taking its address must not reuse its referent's region.
Address-taking uses `addressStorageRoots` and propagates storage through comma,
conditional and assignment expressions. Receiver-data access must not acquire
the local handle's storage. The unmodified `rc_test` checks that receiver data
can still be returned.
`tests/static_results.py` checks handle returns in safe/unsafe bodies and static
constraints. `tests/nested_class_values.py` checks ordinary/static field returns,
aliases, templates and PCM, while executing valid local borrows within functions.

原样 Safe C++ 正例运行采用上游 `SAFE_CXX_BUILD_TESTING=ON` 的
`LIBSAFECXX_PANIC_THROWS` 配置（`libsafecxx/CMakeLists.txt:85`），使故意触发 panic
的异常断言可被测试捕获。兼容报告必须记录配置，并分别保留语法接受、构建、运行退出
及优化级别证据；只有 O0 和 O2 都成功退出才能汇总为官方程序断言通过。这仍不是完整
语义等价或安全性结论。`tests/compatibility_reporting.py` 检查运行参数传播及失败汇总。

Unmodified Safe C++ positive executions use the upstream
`SAFE_CXX_BUILD_TESTING=ON` definition `LIBSAFECXX_PANIC_THROWS`
(`libsafecxx/CMakeLists.txt:85`), allowing intentional panic assertions to catch
exceptions. Reports record this configuration and retain separate syntax,
build, execution-exit and optimization evidence. Only successful exits at both
O0 and O2 count as passed official program assertions, not complete semantic
equivalence or safety. `tests/compatibility_reporting.py` checks runtime flag
propagation and failure aggregation.

规则变更必须说明允许什么、拒绝什么，并覆盖合法程序运行、非法程序诊断、类型别名及
泛型替换、本地与跨 PCM、O0 与 O2。涉及存储的正例使用 ASan/UBSan；涉及 ABI 的项目
另与原始 Clang 对照。无参考编译器执行结果时，明确写“未独立对照”。

Each rule change states what is accepted and rejected, covering execution,
diagnostics, aliases/substitution, local/cross-PCM use and O0/O2. Storage-related
positive cases use ASan/UBSan; ABI changes also compare with pristine Clang.
Without a reference-compiler run, explicitly report no independent comparison.

主要验收入口如下；通过数量必须来自本次实际运行，不能写成固定完成度。

Primary checks follow. Report counts from the actual run, not a fixed completion
percentage.

```sh
python3 tests/class_lifetime_variance.py
python3 tests/array_region_variance.py
python3 tests/generative_lifetimes.py
python3 tests/native_function_addresses.py
python3 tools/test_frontend.py --jobs 4
ctest --test-dir build --output-on-failure -j2
python3 tests/verify_frontend_patch.py
python3 tools/clang_compatibility.py --output /private/tmp/clang2-compatibility.json
```

生产候选状态需要支持范围、未支持组合的拒绝策略、unsafe 库审计、可重建产物、上述回归
及已知问题记录一起验收。本文件、有限测试通过或局部形式化模型都不是生产安全认证。

A production candidate requires an accepted support scope, rejection policy for
unsupported combinations, unsafe-library audits, reproducible artifacts, the
regressions above and a known-issues record. This document, finite tests and local
formal models are not production safety certification.

## 四项合并后的运行语义（2026-10-27）

`clang/AST/CircleRelocation.h` 提供每次查询独立缓存的重定位策略，Sema 与 CodeGen
共享用户钩子、平凡、逐成员、choice、旧 C++ 移动／复制及删除策略。Sema 检查删除、
访问控制和隐式调用效果，CodeGen 按策略构造目标，并更新源对象／字段的条件析构状态。
无用户析构和移动构造的类按 New Circle 规则逐成员重定位，普通构造函数不改变该规则。
phantom 字段继续参与类型／区域约束，但不参与物理子对象重定位。choice 只重定位
激活载荷；异常越过重定位边界必须 terminate，不能回到调用者的 catch。

`relocate(T rhs)` 构造钩子的源码参数拥有源值，内部以引用及隐藏区分参数传递。
它不参加普通构造重载，也不抑制隐式默认构造；初始化列表可以转移部分子对象，
构造结束清理剩余部分。模板和 PCM 保留钩子身份；`operator rel(T)` 与构造钩子
同时出现时拒绝任意选择。删除钩子的 requires 检查形成约束失败，不使编译器崩溃。

旧 C++ 按值 ABI 的析构责任由函数契约携带，直接／间接调用一致。checked 函数
拥有按值参数；legacy 函数保留平台 ABI 的清理责任。记录的定义来源不能覆盖函数
契约，legacy 被调方不能用 `rel` 转走仍由调用者析构的非平凡参数。旧析构的对象
审计通过 `Legacy unsafe value` 明确表达；显式 `unsafe_fn` 包装提供旧 C++ 入口。
`tests/legacy_value_abi.py` 使用独立上游 Clang 生产者验证双向边界、返回、间接调用、
异常及精确移动／析构／释放计数。本批没有引入三个草案调用约定或自动指针适配。

choice 的 OR 分支共享相同名称和类型的绑定，只初始化命中分支。guard 在结构匹配和
绑定之后执行，失败进入后续分支；模板和 PCM 保留 guard，guard 不证明覆盖。
有限构造模式矩阵检查 choice／bool／tuple 的组合覆盖，不能由每一列分别覆盖推出
整个乘积穷尽。过大的模式证明保持拒绝策略。

tuple 字面量的尾随逗号区分已有 C++ 逗号表达式。`f.(tuple)` 和 `f(tuple.[:] ...)`
通过共享求值绑定确保只求值一次，同时保留借用来源及逐字段转移状态。模板字面量
先展开元素参数包，再构造实际 tuple 类型，包含空包和嵌套包。异构遍历使用参数包
与折叠表达式；本批没有增加普通异构 ranged-for 协议。
slice 的地址和元素数共同构造、复制、重定位、传参和返回。
`T~string` 及依赖参数的 `.format(...)` 在实例化后生成具体字符串，类型名文本不作为
跨编译器的稳定身份。

新增 `tests/runtime_semantics.py` 在本地／PCM、O0／O2、普通及 ASan/UBSan 下执行
8 次正例、12 次重定位异常终止和 34 个拒绝用例；旧 ABI 专项另执行 8 次程序。
这些专项及既有区域、高阶、投影、choice、tuple 和 slice 回归共同进入 109 项前端
门禁。本批实测平台为 macOS arm64，未执行独立 Circle 二进制对照。
