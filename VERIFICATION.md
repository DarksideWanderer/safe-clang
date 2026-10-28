# 验证记录（历史记录保留）

当前重新验证见 [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) 和
`build/implementation-baseline/`。下文 2026-10-12 及此前通过记录只绑定当时
快照，不证明当前版本。当前安全元数据协议 v4，AST 序列化格式 45；完整
前端回归和发布检查尚未通过。`subset_status` 与 `full_compatibility_status`
分别报告子集和完整兼容，历史 `validated_candidate` 不代表原样官方兼容。

环境：macOS arm64，LLVM/Clang 22.1.2。原生前端使用仓库内编译的 clang，与 Homebrew LLVM 动态库链接。

检查器指纹随源码变动更新，具体输入和二进制摘要以 build/release-report.json 为准。模块安全元数据协议为 v3；原生 Clang AST 序列化格式为 40。

| 验证 | 结果 |
| --- | --- |
| 插件 CMake/Ninja 构建 | 通过 |
| 插件 CTest：编译、模块图、运行时 | 24/24 通过 |
| 插件编译成功/拒绝案例 | 367 个通过 |
| 漏返回、异常处理退出、整数转浮点范围、隐式转换警告 | 新增 24 个回归通过；关闭 return-type 警告仍拒绝漏返回；-Werror 生效 |
| 原生 Clang 构建与链接 | 通过 |
| into/try_into/checked_into | O2 + ASan/UBSan；65,536 个整数输入、浮点边界、NaN/无穷、3 个 panic、3 个错误的无损转换拒绝 |
| 转换范围模型 | Z3：1,368 个验证条件全部 UNSAT，见 SAFETY-MODEL.md |
| 静态生命周期、借用型异常、未对齐引用、多态构造/析构阶段 | 反例拒绝回归通过 |
| 对象、嵌套字段、基类、数组字段、构造/析构、闭包、再借用、全局初始化 | 编译接受/拒绝回归通过 |
| 接口与实现分开的构造契约、泛型对象、闭包 | ASan/UBSan 运行通过；4 个拒绝案例通过 |
| 泛型只读借用堆容器：增长、移动、读取、销毁 | ASan/UBSan 运行通过；6 个拒绝案例通过 |
| Send/Sync 与 pthread：拥有值、限定作用域独占借用、只读共享 | ASan/UBSan 及 ThreadSanitizer 通过 |
| 并行 mutex 更新、异常解锁、void 回调、unsafe 回调拒绝 | 运行及 7 个拒绝案例通过 |
| 静态生命周期及直接构造的 pinned 自引用对象 | 接受/拒绝回归通过 |
| 原生编译成功/拒绝案例（不加载插件） | 367 个通过 |
| 原生安全函数类型、静态/多参数返回借用、重声明与重载 | 52 个通过；跨 PCM 调用和空指针 trap 通过 |
| 分区、实现单元、跨模块目标文件与链接 | 通过 |
| ASan/UBSan：容器、算术、动态回调 | 通过 |
| 越界/溢出/除零/转换/移位/空回调 panic | 14 个通过，未在 panic 前报告 sanitizer 错误 |
| 原生 token 未被宏替换、强制策略、模式互斥 | 通过 |
| O2 下从 safe PCM 生成代码的无限循环语义 | 通过 |
| Pin 工厂/区域/栈上借用/投影/取出/替换，条件 Send/Sync，原子顺序矩阵 | 插件及原生 ASan/UBSan、TSan；43 个拒绝案例 |
| 命名生命周期、高阶回调、跨 PCM 模板析构与异常回滚 | O0/O2 + ASan/UBSan；20 个拒绝案例 |
| 混合可变/只读借用容器 | 插件及原生 ASan/UBSan；8 个拒绝案例通过 |
| 构建代次发布、失败隔离、预处理依赖和产物摘要 | 插件及原生通过 |
| 原生示例构建、链接、执行 | 返回码 0 |
| 前端补丁从官方 22.1.2 源码包重新应用 | 45 个修改文件无 fuzz 应用，与工作源码一致 |

复现命令：

```sh
cmake --build build
ctest --test-dir build -j 8 --output-on-failure
python3 tools/build_frontend.py --jobs 4
python3 tools/test_frontend.py --jobs 8
python3 tools/regenerate_frontend_patch.py --check
python3 tests/verify_frontend_patch.py
python3 tools/build_modules.py examples/native-modules.json --clang llvm-build/bin/clang --native --output native-module-build
llvm-build/bin/clang++ -std=c++20 -fprebuilt-module-path=native-module-build examples/main.cpp native-module-build/native_example.o native-module-build/safety.o -o native-module-build/example
native-module-build/example
```

范围：结果验证当前实现和回归覆盖，不构成整个 C++ 语言无 UB 的形式化证明。unsafe 实现仍承担其安全 API 不变量的审计责任。对象借用、线程类型规则、显式区域只读借用容器、静态与直接 pinned 构造现已实现。显式 Owner 的混合借用容器、标量参数 Pin 工厂/拥有句柄、顺序一致整数原子现已实现。命名区域、交集、高阶编译期回调和原生借用函数指针已覆盖；Pin 已支持拥有参数、区域、再借用、投影和替换；原子已支持五种内存序、bool 和指针。Rust 全部 GAT/方差/高阶类型运算及协程/union 尚未完整覆盖；无模型的功能采取拒绝策略。详细规则见 README.md。

本次 UB 修复日志：`build/ub-fixes-tests.log`、`llvm-build/ub-fixes-tests.log`。两个原始反例均已重新用原生 safe 模式编译，返回码均为 1。

2026-10-11 转换与生命周期审计日志：`build/conversions-all-tests.log`、`llvm-build/conversions-all-tests.log`。警告策略已调整为只提示可能的数值损失；数值模型证明可用 `python3 tests/prove_conversions.py` 重复。

完整发布检查统一入口：`python3 tools/release_check.py --jobs 4`。最终机器可读状态、源码摘要、二进制摘要及逐项日志路径在 `build/release-report.json`；只有其中的 `validated_candidate` 表示对应版本的全部检查通过。详细生产范围见 PRODUCTION.md。

本轮组合审计新增临时借用失效、按值参数析构、递归 Send/Sync、命名区域跨 PCM 类型一致性、Pin 替换异常回滚以及 CAS 顺序矩阵。完整语义见 LIFETIMES-AND-CONCURRENCY.md，unsafe 实现义务见 UNSAFE-LIBRARY-CONTRACTS.md。上述表格以最终 release-report.json 的退出码为准。

本轮增加 runtime_boundaries（插件／原生）：8 个跨 PCM unsafe 复制、析构和对象回调拒绝案例；Pin 全局分配／释放、safe 回调和稳定常量在 ASan/UBSan 下执行。原生借用额外覆盖条件／逗号／赋值／前置增减的类型身份及不同自有字段分离。最终结果仍以 release-report.json 的源码快照、每项退出码和 validated_candidate 状态为准。

本轮构造与异常路径审计新增 14 个接受／拒绝案例，涵盖成员／基类初始化器移动、构造失败后的参数消耗与未初始化值、局部借用结束、构造／析构 function-try-block 中已销毁成员的访问，以及可能抛出的隐式析构路径。插件和原生前端使用同一分析与回归。

本轮已支持可能抛出的隐式析构，新增 exceptions 专项：自动／临时／返回途中／成员／基类析构、默认数组和默认参数的跨 PCM 检查，O0/O2 + ASan/UBSan，12 个拒绝案例。union 的可变借用、构造、方法、赋值及正常／异常析构会失效活动成员事实。数组隐式填充构造器不再绕过 safe 检查。bitints 专项覆盖所有支持的位宽、131,073 个转换输入及 24 次无提前 UB 的 panic。Lean 局部定理总计 28 条。以上通过状态以对应 release-report.json 为准。

RTTI 异常回归：失败的引用 dynamic_cast 与空指针 typeid 的异常状态检查；关闭常规警告仍拒绝被跳过初始化的值。跨 PCM 的 RTTI 成功／失败路径由 exceptions 专项在 O0/O2 + ASan/UBSan 执行。

本轮修复借用容器字段赋值恢复 moved 状态导致的 ASan heap-use-after-free：4 个跨 PCM 反例均拒绝，普通／显式整体拥有值赋值的 sanitizer 正例通过。borrow_domain 直接执行生产合并／冲突函数的 10,368 个状态组合，旧的父权限并集规则会失败。新增构造数组初始化及 union 真实所有者别名赋值案例，编译案例总计 367 个，CTest 总计 24 项，局部 Lean 定理 28 条。发布结果以同一源码快照的 release-report.json 为准。

2026-10-12 原生 slice 与安全限定符：`unsafe` 类型限定符（声明说明符、指针／
引用声明符、成员初始化器）、`[T; dyn]^` 借用值与其元素数／元素地址／带检查
下标内建、后缀 `~trait`（表达式与类型两种操作数）、`cpy`/`drp`/`mut`/`addr`、
后缀 `^`、`&.`/`&->`、类生命周期实参在类模板特化上的解析、`/static` 内建
生命周期、尾置返回类型限定符并入函数契约、`= trivial`，以及检查模式下的
用户定义字面量后缀。消费接收者允许平凡复制类型的左值接收者。
普通翻译单元的安全模式：`-fcircle-safety` 可用于非命名模块 TU，但仅当源码
写了 `#feature on safety` 才检查；系统头声明不被标记为安全；插件层保持
只接受命名模块。第一类借用模型下 `recv.method()`／`operator->` 自动形成
接收者借用，`T^` 到 `const T^` 有隐式限定转换。`unsafe { }` 不开启词法作用域，
行内成员定义的 `unsafe` 初始化器、尾置返回类型前的 `safe` 后缀、`safe(e)`
requires 原子、`operator[]` 多参数形式与 `&.`/`&->` 的空指针接收者均已对齐。
`tools/test_frontend.py` 全量通过、CTest 24/24 通过、前端补丁 76 个文件
无 fuzz 重放一致。按官方库探针口径
（`-fsyntax-only -x c++ include/std2/std2.h`，`-fcircle-safety -fcircle-borrow-values`）
的错误由 269 条降至 33 条（choice/match 已实现，见 CIRCLE-COMPATIBILITY.md
的专节及其受限说明）。该批剩余错误在 2026-10-13 关闭，见下条。本轮不构成
Circle 兼容或内存安全证明。

2026-10-13：同一探针口径下 `include/std2/std2.h` 以 **0 error、exit 0** 通过
（重复运行一致，仅余库自身 `printf` 的 3 条格式警告）。本轮补齐了切片借用的
常量求值、字面量／切片到 `string_constant` 的转换、原生 tuple 的类型与
`.N`／`.[:]`／`.(...)` 用法、`rel` 后缀与 `rel args...`、`operator rel(T)`
的删除声明与构造函数生命周期列表、`T~is_send`／`T~is_sync`／`__is_lambda`、
库属性族 `[[unsafe::…]]`／`[[safety::…]]`／`[[circle::…]]` 到 `safecpp.*`
注解的映射、检查器对契约存储与依赖读取的处理，以及 checked TU 主文件记录的
按值参数析构 ABI。探针通过不等于库兼容或内存安全证明：分阶段语义与遗留缺口
见 CIRCLE-COMPATIBILITY.md 的"2026-10-13"节。`tools/test_frontend.py` 全量
通过、CTest 24/24 通过、前端补丁 82 个文件无 fuzz 重放一致。

2026-10-13（续）：借用到*类*的隐式转换放行给该类自己的构造函数（`println(sc.text())`
因此选中 `string_view` 重载而不是递归回到 `string_constant`），借用到指针／
引用／标量仍被拒绝；checked 编译定义的记录（含普通 TU 包含的头文件）使用被
调用端析构 ABI，`module;` 片段里的 legacy 头仍保留 C++ ABI。消费者 TU 可通过
前端（`-fsyntax-only`）且无错误；触碰切片借用存储的成员访问在代码生成阶段
给出 `cannot compile this member access through a native borrow yet` 诊断而非
崩溃——切片地址／长度的代码生成仍是待办，见 CIRCLE-COMPATIBILITY.md。本轮
`tools/test_frontend.py` 全量、CTest 24/24、补丁重放 82 文件一致。

原生借用重载偏好仅在至少一个候选目标为原生借用时参与排序；普通 C++ 引用重载沿用原有规则。native_borrows 覆盖成员／自由函数重载在普通翻译单元和 checked module 中的回归。内建一元借用构造入口统一调用原生借用检查与 AST 构造。

checked `&&` 消耗接收者：367 个编译案例包含调用后重用、通过借用消耗、分支／异常合并、方法体内 `*this` 转发及实际派生所有者析构契约；新增跨 PCM 专项在 O0/O2 + ASan/UBSan 执行正例并验证 16 个拒绝案例。原生 `T^` 的两个消耗拒绝反例计入 21 个原生借用拒绝案例。最新发布报告决定该源码快照是否通过所有 gate。

原生 `^^` 与直接字段部分移出：O0/O2 + ASan/UBSan、确切析构次数、字段借用和 18 个拒绝案例；mutable TLS 跨 PCM 的 reset／构造／normal/EH 析构及实参失效包含 14 个拒绝案例。当前回归总计 367 个编译案例、24 个 CTest。以上本轮结果需以匹配当前源码的最终发布报告确认；旧快照不能验证这些改动。

2026-10-12 原生 `:=`／显式销毁／延迟初始化覆盖记录、标量、直接字段、模板、异常与借用持有者，24 个拒绝案例；原生拥有参数覆盖跨 PCM、字段转移、构造委托、虚／间接调用与失败实参清理，6 个拒绝案例。两项专项均在 O0/O2 + ASan/UBSan 下执行。C++ 移动来源权限专项有 16 个拒绝案例；全局效果专项有 14 个拒绝案例；pinned 按值参数不能返回其自身存储中的引用。最新完整检查 14/14 gate、24/24 CTest、367 个编译案例、45 个补丁修改文件、28 条局部 Lean 定理全部通过，并确认源码摘要匹配。报告状态为 validated_candidate。

嵌套字段路径：native_nested_places 在 O0/O2 + ASan/UBSan 下验证重复字段声明的路径身份、分支借用、子树转移／恢复、深层替换、参数／构造委托／异常清理及 10 个拒绝案例。跨 PCM 延迟生成的隐式／默认析构独立检查成员调用，unsafe 成员析构仍被拒绝。此轮完整发布 14/14 gate、24/24 CTest、367 个编译案例、45 个补丁修改文件全部通过，报告源码摘要匹配；原生 AST 格式仍为 40。

原生按值 self：`^^ T self` 是显式对象值参数，跨 PCM 保留拥有标记，使用真实记录参数及原生析构 ABI；O0/O2 + ASan/UBSan 覆盖整值／字段转移、模板、操作符、函数指针、抛出清理与 6 个拒绝案例。完整发布仍为 14/14 gate、24/24 CTest、367 个编译案例、45 个补丁修改文件、28 条局部 Lean 定理通过。报告状态 validated_candidate 且源码摘要匹配。

2026-10-12 生命周期扩展：返回来源集合取消 31 项联合上限，原生单输入借用及 safe_function 类型别名支持生命周期省略，AST 格式为 41。52 个函数类型案例和跨 PCM 间接调用通过；完整发布 14/14 gate、24/24 CTest、367 个编译案例通过，报告为 validated_candidate，源码摘要匹配。尚未实现原生显式生命周期绑定、任意 outlives 关系、完整高阶量化和嵌套类型方差；本轮结果不表示完整生命周期系统已完成。

原生函数生命周期本轮待最终发布验证：`T^/a` 和 `f/(a,b; a:b)` 的绑定／outlives、闭包／区域相等／名字规范化／类型身份／虚函数契约、自动省略与显式接口等价，32 个拒绝案例和跨 PCM O0/O2 + ASan/UBSan 通过，包含普通／泛型 lambda 与 unsafe 类型升级反例。操作符来源映射修正的生命周期专项有 28 个拒绝案例。AST 格式为 42；新补丁涉及 47 个文件。记录类型生命周期实参及完整高阶方差尚未实现。

2026-10-12 全调用临时借用：确认原先接受的 `read_after_reset(owner.get())` 可产生 ASan heap-use-after-free，现原生／插件均硬错误拒绝。23 个全局借用反例在 O0/O2 下通过；最新修复待最终发布重检。共享检查器曾被旧版本覆盖，已备份旧文件并从最新原生副本恢复。

2026-10-12 最新完整发布重检完成：14/14 必需 gate、24/24 CTest、367 个编译案例全部通过。
包含 32 个原生函数生命周期拒绝案例、52 个函数类型案例、28 个生命周期系统拒绝案例、
23 个全调用全局借用拒绝案例，以及 ASan/UBSan、TSan、10,368 个生产借用模型组合与
28 条局部 Lean 定理。原始 LLVM 补丁无 fuzz 重放，实际校验为 46 个文件
（以上“47 个文件”为此前统计，当前以重放结果为准）。AST 格式为 42。
`build/release-report.json` 状态 `validated_candidate`，源码指纹
`b1471bbbab16ff2dd692400778aca12fad29a308d69a1647d52c6289e7d66107`。
Circle 官方文档／库兼容性检查已建立，但官方 stdlib 六个原样示例仍全部不兼容；
此发布结果不表示 Circle 全特性对齐或完整内存安全证明。

2026-10-13 std2.h 消费者程序：除"头文件作为翻译单元 0 error"外，本轮把验收推到
编译／链接／运行。`include/std2/std2.h` 的消费者程序（字面量 `string_constant`
与 `string_view`、`basic_string` 追加、`optional` 的 `.some`／`is_some`／
`is_none`／`unwrap`、用户 `choice` 的 `match`、`vector` 的 `push_back` 与带边界
检查的 `operator[]`、`box`）在 `-fcircle-safety -fcircle-borrow-values` 下
编译、链接并运行，输出与预期一致、exit 0。本轮修正的是切片借用的"地址＋元素数"
代码生成、编译器提供的类值在 `CK_NoOp` 聚合转换下的写入、choice 特化的注解识别
与载荷写入、`.alt` 的期望类型推断、匹配重定位、模板实例化对编译器转换的保留、
`?:` 的 noreturn 操作数，以及 choice 默认构造函数。回归：`tools/test_frontend.py`
（367 个编译案例及全部运行时／拒绝案例）、`ctest --test-dir build` 24/24、
`tests/verify_frontend_patch.py`（83 个文件无 fuzz 重放）与
`tools/release_check.py` 全部必需 gate 通过。

2026-10-13（续）match 模式、自定义重定位与线程契约：`tests/choice_patterns.py`
覆盖 `.alt`/`_`/`true`/`false`/值/范围（`lo...hi`）/`|`/嵌套载荷模式与 6 个
拒绝；`tests/relocation_operators.py` 覆盖 `rel`、match 绑定与 choice 载荷经
`operator rel(T)` 重定位；`tests/tuple_call.py` 覆盖 `f.(tuple)` 展开；
`tests/nested_borrows.py` 覆盖整条切片借用的 `cpy`/`rel` 与 `T^^` 借用的借用；
`tests/conditional_contracts.py` 覆盖 `[[unsafe::send(T~is_send)]]` 按实例求值
（接受/拒绝两侧）与 `T~is_send` 的取值。五项均接入 `tools/test_frontend.py`。
