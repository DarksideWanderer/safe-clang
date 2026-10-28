> 最新进展（2026-10-27，嵌套聚合再借用）：修复数组、嵌套记录及临时按值实参
> 的父借用关系丢失；来源重叠的每个元素均须授权，分支关系只保留共同事实。
> 数组后续初始化不能使此前的临时借用失效；具名聚合转移保留已检查的权限，
> 借用句柄转移还会检查 referent 存活，拒绝过期来源及转移后重用。
> 新专项通过 8 次本地／PCM、O0／O2、普通和 ASan/UBSan 运行，33 类／132 次
> 带诊断归属的拒绝。最终固定版本通过前端 **112/112**、CTest **26/26**、
> 原样官方正例 **14 文件／54 配置**、Clang 差分 **13/13** 和 **104 文件**
> 无 fuzz 重放，源码／二进制摘要无漂移。当前报告为
> `build/nested-aggregate-audit/final-acceptance/acceptance.json`。
> phantom／间接存储、union、基类和自定义析构继续使用既有专属模型，
> 不把本轮聚合修复推成任意构造／存储行为的完整兼容。

> 前一批进展（2026-10-27，slice 运行语义与句柄限定修复）：补齐固定数组借用到
> slice 的地址／长度转换，保留父借用；接收者、地址／长度和索引绑定后只求值
> 一次，负下标及宽整数在窄化前检查，越界使用 abort panic。模板里的非依赖
> 下标可重建绑定，修复官方头文件实例化崩溃。借用后写的 const／volatile 现在
> 保留到类型与 PCM；只读句柄不能被写入，共享弱化不能复制独占外层权限。
> 新专项通过 8 次本地／PCM、O0／O2、普通及 ASan/UBSan 正例、24 次边界 panic、
> 46 个拒绝用例、4 次原样官方越界程序运行和官方错误恢复检查。
> 本次重新构建并完成四项整批验收：前端 **111/111**、CTest **26/26**、官方
> 正例 **14 文件／54 配置**、Clang 差分 **13/13**、**104 文件**无 fuzz 重放；
> 源码和二进制摘要一致。报告为 `build/slice-runtime-audit/final-acceptance/acceptance.json`，
> 中间官方 vector 回退的失败报告保留于同目录的 `acceptance/`。
> 原样官方正例的 O0／O2 断言均通过，34 个编译反例仍为 19 个预期归属、15 个
> 未归属、0 崩溃、0 意外接受；panic 从 12/16 提升到 14/16，剩余两次构建缺少
> `INT_MIN` 声明。兼容矩阵绑定当前固定版本，仍有 29 份文档待复核、原始
> Circle stdlib 0/6 和独立 Circle 对照等缺口。另记录原生数组聚合嵌套独占借用
> 的父关系保守拒绝，不把它隐藏为通过。详见 [compatibility/README.md](compatibility/README.md)。

> 前一批进展（2026-10-27，兼容缺陷与发布证据）：在前一批四项通过的固定版本上，
> 原样官方 `string_view1.cxx` 揭示数组经用户定义转换参与赋值时的 Sema 崩溃。
> 修复数组到 slice 的标准转换生成路径，统一构造地址／长度，检查 const／volatile
> 和可变借用许可，拒绝未知固定长度；新增本地／PCM、O0／O2、普通及 ASan/UBSan
> 8 次执行、10 个拒绝用例和原样官方诊断恢复检查。新固定版本前端 **111/111**、
> CTest **26/26**、默认 Clang 差分 **13/13**、**103 文件**无 fuzz 重放及构建／
> 格式检查全部通过，源码与二进制摘要无漂移；门禁日志也记录摘要。
> 证据见 `build/compat-release-audit/acceptance/acceptance.json`。
> 兼容机器清单从旧 17 个大类扩展至 92 项，覆盖 New Circle 的 41 个独立指令，
> 仍明确保留 29 份历史文档的语义复核和反例缺口。矩阵拒绝过期报告和缺失日志身份，
> 不把测试路径存在当作通过。34 个原样编译反例现有 19 项预期规则归属、15 项未
> 归属、0 崩溃、0 意外接受；panic 检查 12/16，原始 Circle stdlib 0/6。
> `release_check.py` 改为构建后冻结二进制，并在每道门禁前后核对。
> 逐项结果见 `build/compat-release-audit/features.md`；清单与复现说明见
> [compatibility/README.md](compatibility/README.md)。兼容清单及完整发布尚未完成。

> 前一批主线（2026-10-27，四项合并完成验收）：按选定的 Circle 兼容扩展范围，
> 区域关系闭环、通用高阶关系、泛型投影和运行语义均纳入同一固定版本门禁。
> 在前一批区域／泛型实现上补齐 `operator rel(T)` 与 `relocate(T rhs)` 的共享
> 策略、用户／默认／平凡／删除钩子、递归成员及激活 choice 载荷重定位、源对象
> 剩余子对象清理和 noexcept 终止。普通构造函数不再让容器包装类绕过逐成员
> 重定位；phantom 类型约束不被误作物理子对象。非平凡参数析构 ABI 按函数契约
> 决定，独立上游 Clang 验证双向旧 C++ 互操作，拒绝 legacy 被调方转走调用者
> 仍负责析构的参数。补齐 OR 共同绑定、guard 与模板保留、嵌套乘积穷尽性，
> tuple 点调用／整包调用单次求值、嵌套及空参数包实例化、借用来源、slice 地址／
> 长度传递及实例化后的 `~string`／依赖 format。新增专项通过 8 次运行语义执行、
> 12 次异常终止检查、34 个拒绝用例及 8 次旧 ABI 互操作执行。
> 本次从构建到验收全部通过：前端 **109/109**、CTest **26/26**、原样官方正例
> **14 文件／54 配置**、默认 Clang 有限差分 **13/13**、**103 文件**无 fuzz
> 补丁重放及差异格式检查。源码与二进制摘要无漂移；失败的中间版本另行保留，
> 不计入通过。证据见 `build/four-pillars/acceptance.json`，重现命令和语义边界见
> [FOUR-PILLARS.md](FOUR-PILLARS.md)。本批运行验收平台为 macOS arm64；未执行
> 独立 Circle 二进制对照，不代表整个 Circle 语言或所有平台 ABI 已完成。

> 前一批主线（2026-10-27，Circle 兼容捕获与泛型关系扩展整批验收）：按选定的
> Circle 兼容扩展范围补齐外层区域捕获、类区域参数四点方差和泛型关联类型投影。
> 每层原型独立绑定，支持词法遮蔽、跨层替换、空包后捕获重编号、嵌套参数逆变及
> 正确的量词先后关系；共享类型图按固定点计算方差，可变存储保持不变。
> 关联投影保留模板参数身份、限定名和包元素环境，组合别名链、成员别名模板、
> 偏特化及包索引。捕获型回调逐区域追踪值来源，包含类字段、返回、聚合初始化、
> 复制、重绑定与 CFG 合流；双区域回调的输入／输出来源分别验证，支持直接／间接
> 工厂调用及临时返回对象的回调成员调用。未知或有歧义的投影仍不能提供安全证明。
> 新专项通过 2,768 条外层捕获、132 条类参数方差断言；泛型投影 396 项及 8 次运行，
> 回调值 69 次编译及 8 次 O0/O2 普通和 ASan/UBSan 运行；原 6,144 条关系断言保留。
> 最终固定二进制门禁：前端 107/107、CTest 26/26、官方正例 14 文件／54 配置、
> 默认 Clang 有限差分 13/13、100 文件无 fuzz 补丁重放；源码与二进制摘要无漂移。
> 证据见 `build/complete-region-system/acceptance.json`；参考语义与开放范围见
> [SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md#circle-兼容捕获与泛型关系扩展2026-10-27)。
> 外层捕获是本仓库明确规定的 Circle 兼容扩展；未引入 Rust trait／GAT，未执行
> 独立 Circle 二进制对照，本批不代表整个编译器已经完成。

> 前一批主线（2026-10-27，通用高阶关系补齐验收）：在已有共享关系层上补齐独立绑定
> 作用域、方向性替换、共享协变、可变内容不变性和嵌套参数逆变组合的本批范围。
> 显式区域借用包、类值／类借用包保留绑定、投影、outlives 和返回来源；规范化前取得
> 可实例化的具体类定义，消除实例化顺序导致的契约身份差异。共享 static 查询沿
> outlives 闭包传播，空包删除 static 参数后仍执行隐含要求；安全／unsafe 的直接、
> 间接、模板和构造调用均验证，局部视图句柄不能借永久数据逃逸。
> 独立生命周期集合模型通过 6,144 条本地／PCM 关系断言；参数包专项通过 106 条
> 类型身份断言、79 次编译和 8 次 O0/O2 普通及 ASan/UBSan 执行。原有高阶 586 项、
> 数组区域 150 项、ABI 错配拒绝、CFI/KCFI 及 24 层重复类型图全部通过。
> 固定二进制门禁：前端 104/104、CTest 26/26、官方正例 14 文件／54 配置、
> 默认 Clang 有限差分 13/13、100 文件无 fuzz 补丁重放；摘要无漂移。
> 证据见 `build/higher-relations-complete/acceptance.json`。开放范围及剩余限制见
> [SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md)；未执行独立 Circle 二进制对照。

> 前一批主线（2026-10-26，初始化图可用性整批验收）：修复声明分类器反复遍历语法／
> 语义初始化列表的共享子树、聚合借用来源重复递归，以及 CFG 父关系查询遍历整个
> 翻译单元的三处重复工作。遍历按检查上下文去重，父关系保留所有传入边，来源只在
> 同一 State 查询内复用；隐式填充、独占别名、兄弟实参副作用和异常检查继续保留。
> 原 25 层探针从超过 30 秒改为本机约 0.11 秒正确拒绝逃逸。原生／插件分别通过
> 51 次本地／PCM 编译和 8 次运行，覆盖 40 层值与借用的 O0/O2、ASan/UBSan。
> 新共享头已纳入两套构建、源码复制及 PCM 检查器指纹。
> 固定二进制门禁：前端 102/102、CTest 26/26、官方正例 14 文件／54 配置、
> 默认 Clang 有限差分 13/13、100 文件无 fuzz 补丁重放；摘要无漂移。
> 证据见 `build/initializer-traversal-acceptance.json`。25 层 T+ 链的显式 `/a`
> 仍受旧区域计数深度限制而被拒绝，已保存当前二进制的复现；该泛型语义缺口、后续
> 运行语义和完整兼容性仍待完成，未执行独立 Circle 二进制对照。

> 前一批主线（2026-10-26，泛型区域投影整批验收）：字段区域改为按模板参数身份映射，
> 统一重复、重排、嵌套、别名、参数包、偏特化与可唯一恢复的显式特化；来源检查和
> 类区域方差共用映射。修正数组别名区域计数、未标记参数包虚增区域，以及数组借用
> 载荷与句柄存储的混淆；混合 static 区域逐项保留，未知映射不能提供安全证明。
> 专项 236 项本地／PCM 检查和 8 次 O0/O2 普通及 ASan/UBSan 执行通过。
> 固定二进制门禁：前端 101/101、CTest 25/25、原样官方正例 14 文件／54 配置、
> 默认 Clang 有限差分 13/13、100 文件无 fuzz 补丁重放；摘要无漂移。
> 证据见 `build/generic-projections-acceptance.json`。额外 25 层嵌套构造探针在
> 30 秒内未完成，深嵌套性能仍待处理；未执行独立 Circle 二进制对照，也不宣称
> 任意泛型投影或完整编译器已经完成。

> 前一批主线（2026-10-26，通用高阶关系整批验收）：共享关系层实现独立绑定作用域、
> 方向性替换、共享协变／可变内容不变性及嵌套函数参数逆变组合。补齐原生 `T^`、
> 只读数组和成员函数指针的递归关系与运行时签名视图；模板参数包展开按原位置重写
> 绑定、类区域、outlives 和返回来源。直接成员数据指针与可写引用槽不能借转换
> 改写回调契约。高阶专项 586 项、数组专项 150 项本地／PCM 转换通过，并覆盖
> O0/O2、ASan/UBSan、CFI/KCFI、ABI 错配拒绝和 24 层重复类型图。
> 固定二进制门禁：前端 100/100、CTest 25/25、原样官方正例 14 文件／54 配置、
> 默认 Clang 有限差分 13/13、100 文件无 fuzz 补丁重放；验收期间摘要无漂移。
> 证据见 `build/higher-relations-acceptance.json`，语义和限制见
> [SAFETY-ARCHITECTURE.md](SAFETY-ARCHITECTURE.md)。任意外层区域捕获、完整泛型
> 关联投影等仍未纳入；本批不代表完整 Circle 或 Rust 类型系统。

> 最新主线（2026-10-18，显式安全效果与借用槽数组）：`safe(e)` 改为真正的
> 表达式 trait（`ET_IsSafeExpr`），在依赖上下文中保持 value-dependent，
> 模板实例化时用具体调用目标重新求值。函数类型新增显式安全位：只有写出的
> `safe`、已检查 lambda 或命名 safe 模块的默认效果才算显式安全；
> `unsafe_fn` 与普通 TU 中无后缀的定义保留 checked 调用效果但不是显式安全。
> 该位进入 `FunctionType::ExtInfo`（16 位）、PCM 序列化、名称修饰和函数指针
> 转换；官方 `thread2.cxx` 现在按预期被拒绝，`sync.cxx`、`thread_test` 与
> 54/54 官方正例继续通过。`safe(e)` 的操作数按未求值上下文检查。
> 借用槽数组 `const T^/a values[N]` 现在把声明区域投影到每个元素：聚合
> 初始化、隐式数组复制构造、模板 `T+` 字段、PCM 消费和逐元素读取均可用；
> 来源改写、区域错配、局部逃逸和静态借用逃逸被拒绝。
> 新增 `tests/borrow_slot_arrays.py`、`tests/safe_effect_atom.py`。门禁：
> 完整前端 87/87；CTest 25/25；官方 Safe C++ 正例 54/54 配置。
> 仍不标记 100%：官方 `vector1.cxx` 仍被接受（`vector<T+>` 的 phantom 区域
> 还没有字段外表示）；类值数组 `View/a items[2]` 仍被拒绝；基类生命周期
> 实参 `: Base/a` 尚未解析；跨模块矩阵未开始。

> 最新主线（2026-10-18，门禁可信化）：单模块安全基础的完整门禁重新对齐到
> 当前源码。发现 `build/ModuleSafety.so` 是数小时前的旧产物，CTest 实际在测
> 旧检查器；同时在未定义 `MODULE_SAFETY_BUILTIN` 的出树插件构建里，
> `FieldDecl::isCirclePhantom()` 与 `applySliceBoundEdge()` 两处使用缺少条件
> 编译保护。现已在 `src/FlowAnalysis.cpp` 加回保护，并让
> `tests/borrow_domain.py` 优先使用补丁头文件与 `llvm-build` 的
> `libclang-cpp` 编译。重建插件后 CTest 25/25、完整前端 85/85、官方
> Safe C++ 正例 14/14 文件（54/54 配置）、99 文件补丁无 fuzz 重放全部通过。
> `native_lifetimes` 37 个拒绝、`template_lifetime_binders` 34 个拒绝、
> `slice_rebuild_regions` 16 个拒绝、`native_relocation` 18 个拒绝、
> `native_replacement` 24 个拒绝均通过。
> 仍不标记 100%：官方反例 34 个中 32 个被拒绝、2 个仍被接受
> （`thread2.cxx`、`vector1.cxx`），且被拒绝者尚未带出官方期望的诊断归属；
> panic 反例 16 项中 4 项构建失败（`divide_overflow`、`subscript_slice`）；
> Circle 自带 stdlib 示例 0/6、原始头文件探针 0/4；跨模块契约与 ABI 矩阵
> 尚未系统开展。

> 最新主线（2026-10-18）：`T+` 的命名生命周期与外层 hoisting 已打通。
> `Holder<View>/a`、`Holder<const unsigned^>/a` 与
> `PairHolder<View,View>/a/b`、`Holder<Pair2<View,View>>/a/b` 以及 `T+` 类的显式特化可以在安全的返回类型和局部变量中显式绑定；
> `T+` 参数只在其实际模板实参携带生命周期时生成内部区域，
> 因此 `optional<unsigned>` 的普通拥有返回值不会被误判为借用。调用点必须把
> 返回值的来源绑定到同名参数，生命周期不匹配、局部 owner 逃逸和数量错误均
> 被拒绝。另补了泛型拥有字段在构造抛异常、替换抛异常和成功替换时的析构计数。
> 门禁：完整前端 84/84；CTest 25/25；官方 Safe C++ 正例 54/54 配置；
> `template_lifetime_binders.py` 在 O0/O2 × ASan/UBSan 下通过 33 个拒绝案例；
> `native_relocation.py` 的泛型抛异常路径通过。多区域 `T+` hoisting 和显式
> 特化提升已覆盖直接字段；依赖参数的 `T+` 生命周期数量在替换后也会重新校验。
> 嵌套复合多区域 `T+` 已覆盖三层与混合字段顺序，参数包 `Ts+` 的区域数量、
> 局部投影和交换来源拒绝也已通过；运行期独立 slice 子区间现在要求显式的
> 起点与长度边界检查，边界事实在写入或调用后失效。完全未知分配的 raw
> pointer 仍按保守拒绝处理，四项均不标记 100%。

> 最新主线（2026-10-17，AST90）：官方 `rc_test` 与 `ref_cell_test` 的编译、
> 链接、运行闭环完成。`match` 生成的主体/绑定来源现在通过独立的
> `MatchOrigins` 保留，既能在绑定作用域结束后恢复返回借用来源，也不会把
> 已结束的 loan 留在冲突集合里；`borrow(self const^)` 中
> `.some(b) => rel b` 的返回来源可追到 `self`。mutable deref 的普通
> payload 绑定会真正搬迁 payload 并清空 choice tag，`choice_match` 的
> “消费后拒绝”与 ASan/UBSan 双释放检查均通过。门禁：完整前端 80/80；
> 官方 `rc/ref_cell` O0/O2 × plain/ASan+UBSan 八次运行全部通过；官方正例
> 通过数由 6/14 提升到 7/14。剩余官方缺口为
> `match/ptr1/string/string_view/sync/thread/tuple`，跨模块仍按用户要求暂缓。

## 2026-10-17：AST90 match 来源保留与 rc/ref_cell 返回借用

* **返回借用穿过 match**：`resolveMatchStorage` 只在 match subject/binding
  作用域结束时把 loan roots 移入 `MatchOrigins`，而不是继续保留一个活跃
  loan；`directMatchBindingRoots` 剥离 `ExprWithCleanups` /
  `CXXBindTemporaryExpr`，并用 `safecpp.panic` 标注识别 noreturn 分支。
  `ref_cell::borrow` 的 `.some(b) => rel b` 因此能把返回值来源追到
  `self`，不再报 `std2.h:1436/1437`。
* **match 绑定所有权**：mutable deref 的普通 payload 绑定按值 relocation；
  CodeGen 在 payload relocation 后清空所属 choice 的 tag。`match(mut *p)`
  仍保持借用/watch 语义。
* **重定位运算符回归**：`tests/relocation_operators.py` 按官方
  `optional/cow` 示例的拼写使用显式 `rel`，验证用户定义 relocation
  operator 在 payload 搬迁时只执行一次。
* **验证**：完整前端 80/80（8 jobs）；官方 `rc_test`、`ref_cell_test`
  O0/O2 × plain/ASan+UBSan 八次运行通过；官方正例 7/14。四项仍不标记
  100%，跨模块未开始。

> 最新主线（2026-10-17，AST89）：官方 `optional_test.cxx` 的编译、链接、运行
> 闭环完成。`match (...) -> expected<T, E>` 的依赖结果类型现在传入每个
> `.alternative` 分支，`.ok`/`.err` 不再退化为丢失模板实参的
> `InjectedClassNameType`；choice 载荷 union 在模板实例化后恢复具体字段，
> 避免同类型 `ok`/`err` 字段歧义而只写 tag。新增回归覆盖 `ok_or`、drop-and-
> replace、`take_if`、可变借用实参重借和返回局部 choice。原样
> `optional_test.cxx`、`vector_test.cxx`、`box_test.cxx` 与
> `tests/std2_consumers.py` 均在 O0/O2 × plain/ASan+UBSan 下通过。
> 门禁：完整前端 80/80、CTest 25/25、Clang 差分 13/13、99 文件补丁无 fuzz
> 重放。剩余缺口为官方 `match/rc/ref_cell/string/string_view/sync/thread/
> tuple` 测试，以及跨模块契约（按要求暂缓）；四项仍不标记 100%。

## 2026-10-17：AST89 官方 optional 与依赖 choice 分支结果

* **依赖 choice 的结果类型**：`ParseCircleMatchExpression` 把 `-> expected<T,E>`
  记录为每个 arm body 的 expected type。此前的 `.ok`/`.err` 只按备选名查找，
  于是依赖 choice 的值被构造成只有 pattern 身份的 injected class name；模板
  实例化虽然把外层条件表达式替换成 `expected<int,int>`，真/假分支仍保留
  `expected<T,E>`，CodeGen 在 `std2.h` 的 `ok_or` 中崩溃。
* **实例化后的 union 字段**：`TransformInitListExpr` 现在用替换后的 choice 类型
  恢复 payload union 的具体类型和 `InitializedFieldInUnion`。当 `ok(T)` 与
  `err(E)` 都是 `int` 时，CodeGen 不再因同型字段歧义而只写 tag、留下未初始化
  payload。
* **legacy ABI 边界**：隐式返回记录搬迁只用于 safe 模块或显式 `safe` 函数，
  不再改写 `-fmodule-unsafe` 中未检查函数的返回语义；legacy C++ 模块继续与
  原版 Clang IR 一致。
* **新增回归**：`tests/optional_lifecycle.py` 编译并运行原样官方
  `optional_test.cxx` 及 `ok_or`（ok/err 两路）、`optional<vector>` 的
  drop-and-replace、`take_if`、返回局部 choice；全部为 O0/O2 × plain/
  ASan+UBSan。
* **验证**：完整前端 80/80；CTest 25/25；默认 Clang 差分 13/13；
  `verify_frontend_patch.py` 对 99 个补丁文件无 fuzz 重放；官方
  `optional_test.cxx`、`vector_test.cxx`、`box_test.cxx` 和
  `std2_consumers.py` 四种配置全部通过。
* **仍待完成**：官方 `match/rc/ref_cell/string/string_view/sync/thread/tuple`
  测试仍有不同缺口；`T^` 参数模板推导、部分 const 投影及跨模块组合按用户
  要求继续保留。保守估计：借用与生命周期 95%、拥有转移与替换 94%、
  析构与异常清理 92%、safe/unsafe 单模块边界 93%。

> 最新主线（2026-10-17，AST88）：单模块安全基础的首个官方端到端验收闭环完成。
> 原样 Safe C++ `vector_test.cxx`（含 `vector<box<int>>` initializer-list）在
> O0/O2 × plain/ASan+UBSan 四种配置下编译、链接、运行全部通过；原样
> `box_test.cxx`、`drop.cxx` 与 `tests/std2_consumers.py` 同样通过。关键修复是
> `std2::initializer_list` 的析构责任：底层数组不再单独注册临时析构，未消费元素
> 由 `initializer_list` 析构器销毁，`advance` 标记已搬迁元素。
> 门禁：完整前端 80/80、CTest 25/25、默认 Clang 差分 13/13、99 文件补丁无
> fuzz 重放。仍待完成：官方 `match/optional/rc/ref_cell/string/string_view/
> sync/thread/tuple` 测试的剩余 Sema 缺口、`T^` 参数模板推导、部分 const 投影，
> 以及跨模块契约（按要求暂缓）。Circle 自家 `stdlib/*.cxx` 探针属其他语言特性，
> 不计入本阶段。

## 2026-10-17：AST88 initializer_list 搬迁责任与官方 vector_test

* **问题**：`std2::vector(initializer_list<T>)` 通过 `relocate_array` 把底层数组
  中的元素搬到容器，再调用 `ilist^.advance()` 标记已消费。CodeGen 仍为底层数组
  注册了一次独立的临时析构清理，于是 `vector<box<int>>` 的元素在构造结束后被
  提前销毁，容器只留下悬垂句柄；官方 `vector_test.cxx` 因此在读取
  `*xs[idx]` 时中止。
* **修复**：`CGExprAgg.cpp` 的 `CXXStdInitializerListExpr` 路径对
  `std2::initializer_list` 直接初始化底层数组存储，不再注册数组自身的临时析构。
  未消费元素仍由 `initializer_list` 析构器按 `[_cur, _end)` 销毁；元素构造中途
  抛异常时，部分构造数组的 EH 清理保持原有行为。
* **回归**：`tests/std2_consumers.py` 增加 owning `vector<box<int>>` 的
  initializer-list 构造与逐元素读取，覆盖 O0/O2 × plain/ASan+UBSan；原样官方
  `vector_test.cxx` 四种配置全部通过。
* **验证**：前端回归 80/80；CTest 25/25；默认 Clang 差分 13/13；
  `verify_frontend_patch.py` 对 99 个补丁文件无 fuzz 重放；`box_test.cxx` 与
  `std2_consumers.py` 通过。
* **仍待完成**：官方 `match/optional/rc/ref_cell/string/string_view/sync/
  thread/tuple` 测试尚有不同的 Sema/库表示缺口；`T^` 参数模板推导与部分 const
  投影仍保留；跨模块契约按用户要求暂缓。四项进度不标记 100%。

## 2026-10-17：AST85 模式借用投影与虚 consuming receiver

这一轮把两处仍会破坏“单模块安全基础”闭环的组合补齐：

* `match` 的 `^payload` 绑定是 subject 的再借，而不是对同一 choice 的第二笔
  独占 loan。绑定 loan 现在继承 subject 及其来源作为 ancestors；同一路径上的
  subject/value 不再互相报冲突，但同臂内再借整个 choice 或跨臂使用仍按
  “access conflicts with a live exclusive borrow / mutation conflicts with a
  live borrow”拒绝。
* `static_cast<Base&&>(local_derived).take()` 现在允许虚 consuming receiver
  的动态分派。该写法按整对象消费保守处理：消费后再命名派生对象报 moved；
  经 `Base&&` 引用消费仍报 consume through a borrow；非平凡且未审计的
  moved-from 析构仍拒绝。字段级 partial move 由下一节补齐。
* 回归补上 `tests/choice_borrow_patterns.py` 的 subject/pattern 正例与两条
  拒绝，以及 `tests/native_function_addresses.py` 的 virtual base-cast 正例、
  consume-then-use 和 consume-through-borrow 反例。

验证：`tools/test_frontend.py --jobs 8` 80/80；`ctest -j 8` 25/25；默认 Clang
差分 13/13；`tests/verify_frontend_patch.py` 对 99 个补丁文件无 fuzz 重放；
证据日志为 `build/implementation-baseline/frontend-ast85.log` 与
`build/implementation-baseline/ctest-ast85.log`。按单模块口径，借用/生命周期、
拥有转移、析构清理与模块调用边界均已有端到端回归；跨模块契约仍按用户要求暂缓。

## 2026-10-17：AST86 字段级 partial move 与官方 box_test

* consuming receiver 现在接受 `static_cast<Part&&>(owner.field).take()`：只把
  该字段及其拥有子树标为 moved，父对象的其他字段仍可读；字段再使用、异常
  路径上的再使用、经借用消费，以及父类型有自定义未审计析构、字段自身非平凡
  且未审计析构的组合均拒绝。
* 嵌套字段 `owner.outer.inner.part` 与虚基类字段
  `static_cast<Base&&>(holder.base).take()` 均已实跑；后者确认动态分派到
  `Derived::take()`。
* 新增 `tests/partial_moves.py` 覆盖 O0/O2、普通及 ASan/UBSan 的字段/嵌套/
  虚分派/异常路径和 7 条拒绝；`consuming_receivers.py` 也补了跨 PCM 的字段
  正例与“字段消费后再用”反例。
* 原样 Safe C++ `test/box_test.cxx` 现在通过 O0/O2 + ASan/UBSan 的编译、链接
  和运行；`tests/official_box_test.py` 固定该原样源码，避免回到旧的头文件
  检查清单阻塞。

验证：`tools/test_frontend.py --jobs 8` 80/80；`ctest -j 8` 25/25；默认 Clang
差分 13/13；99 个补丁文件无 fuzz 重放。证据日志：
`build/implementation-baseline/frontend-ast86.log` 与
`build/implementation-baseline/ctest-ast86.log`。剩余跨模块契约按要求暂缓；
完整 dyn/coherence 仍不在本轮单模块安全基础验收内。

## 2026-10-17：AST87 postfix receiver loan 与 generative receiver 来源

* postfix `v^` 在成员访问前现在形成与 prefix `^v` 相同的第一类 borrow value，
  并在后续后缀解析期间保留 mutable context。`v^.push_back(...)`、
  `v^.slice()` 和 mutable slice 元素写入因此可解析；显式 `self^` 重载优先于
  `const self^`，`const` referent 仍不能绑到可变 receiver。
* `slice_from_raw_parts(self.data(), self.size())` 这类从当前显式 receiver 派生
  的 generative slice 不再报“conflicts with a live borrow”：receiver 自己的
  loan 是该结果的来源，只有当互补性不成立或另有一笔独立借用时才拒绝。
* `tests/std2_consumers.py` 增加 postfix receiver、mutable slice 重写与输出断言；
  完整 gate 仍为 80/80。

官方 `vector_test.cxx` 的前进范围：`vec^.push_back` 与 `s[0] = 17` 的 mutable
slice 选择已通过；剩余失败集中在 `(^vec)[0]` 的模板/投影、`assert_eq` 对
`T^` 参数的推导、部分 const `operator[]` 投影、`int^ const^` 声明和
initializer-list 构造。
这些是后续的模板/库表示工作，不把本轮单模块安全基础回归标成完整官方兼容。

验证：完整前端 80/80；CTest 25/25；默认 Clang 差分 13/13；99 文件补丁无
fuzz 重放；原样 `box_test.cxx` 仍通过 O0/O2 + ASan/UBSan。

> 最新主线（2026-10-14）：优先 generative 生命周期，再推进安全基础的其余缺口；暂缓跨模块新实现。当前 AST79：逐条复核了借用与生命周期的五个缺口——对象尺寸/指针数据流与 generative slice 运行期 extent 属"按设计的拒绝且官方并不需要"，`*(*b)` 与裸 `s.append(...)`/`v.push_back(...)` 经官方资料证实是**我们测试写错的拼写**（官方是 `*p`/`**p` 与 `mut s.append(...)`），真正的两处缺口是"未知来源指针的常量偏移"与"`self^` 方法体内对自身借用的再借"，均已关闭。此前 AST77 把模式选择改为只由编译指令指定（`#feature on safety` 已废弃、单模块即可、策略文件可选）并把 gate 改为多核。证据 `build/implementation-baseline/row1-gap-audit-evidence-v79.json`。完整 frontend gate 仍因 `std2_consumers.py` 退出 1，但消费者程序本身已无 Sema 错误，红的是**官方头文件自身的检查清单**（首项即 5 个字面量运算符的 `static` 契约）。

> 当前用户要求（2026-10-13）：安全模式只由编译命令选择，弃用 `#feature on safety` 的模式选择作用。历史章节中依赖 directive 才检查普通 TU 的描述已失效。命令模式与非系统头文件函数体检查专项已通过；完整兼容与发布验收仍未完成。PCM 的额外模式改造暂不处理。

# 当前实施与证据：2026-10-13

目标仍为固定 Circle、Safe C++ 与 Clang 的完整兼容；当前未达到。
平台范围为 macOS arm64。三个参考 Git 树均干净，提交分别为
Circle `b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc`、Safe C++
`889685274438ca20344d4d9cb472e4392c4e35a9`、mdspan circle 分支
`774a1f0c401144d88fdf4d655a70b777b879f4b4`。没有可用参考 Circle
二进制，未声称 Circle 二进制差分结果。

按当前实施优先级，主线为原样 Circle safety 兼容和生产语义：先解决依赖
类型 match、调用点生命周期约束，以及原生 interface/impl/dyn 和关联类型；
通过原样库的编译、链接、运行与有针对性的安全负例验收。默认 Clang
差分保留为回归门槛。保守拒绝未建模功能不计作该功能兼容完成。

工作区根没有 Git；`build/implementation-baseline/initial.json` 保存实施前
源码摘要。展开 LLVM 树有 16 个文件与原补丁摘要不同，已保留既有修改，
备份覆盖的 83 个文件及原补丁，重建累计补丁并验证无 fuzz 重放。

当前修改关闭两个入口：未建模的 leading `where` 生命周期种类约束不能
被静默丢弃；源码不能伪造 compiler-owned native/thread 元数据
来跳过 safe 函数检查。关闭扩展时 annotation 的上游行为保持不变。
安全 PCM 协议从 v3 更新至 v4；新增 `CircleMatchExpr` 后 AST 格式由 44
更新至 45，旧 PCM 需重建。上述检查依赖可信编译与构建链，不证明对抗任意
PCM、动态库或二进制替换的能力。

后续实际语义修复：按固定 Circle `new-circle/README.md` 的规定，将范围
模式 `lo ... hi` 改为半开区间；界值保留自身 C++ 整数类型，避免被截为
操作数的窄类型。按原样 Safe C++ `std2.h` 中 `.some(^x)` 的用法，修复
模式绑定遗漏借用类型的问题，保留共享 const、可变借用和载荷的析构责任。
`match_ranges.py` 与 `choice_borrow_patterns.py` 已在两个 checked 模块的
PCM 链上通过实际 O0/O2、constexpr（范围专项）、ASan/UBSan 及具体负例。
返回借用的 match 投影仍因未知来源而拒绝，尚未实现完整返回来源推导。
这些专项不代替原样官方整文件验收。

依赖类型 match 现在保留完整模式树、绑定声明、分支体及显式结果类型，
并通过 PCM 读写；实例化时重新确定载荷类型、重建绑定，再检查分支和
降级。修复 bool 匹配的 constexpr 值转换，以及模板 choice 非平凡析构
生成时机和存储联合标记。`dependent_match.py` 验证了两个 checked PCM、
choice／整数／bool／嵌套共享借用、constexpr、拥有载荷返回／析构／异常
清理，实际 O0/O2 + ASan/UBSan；6 项实例化／定义反例因具体预期规则拒绝。
补丁当前覆盖 89 个文件；无 fuzz 重放以最新日志为准。完整模式语法、
match 出现在需要表达式名称修饰的签名、返回借用来源推导，以及构造表达式
中的完整 choice 预期类型推导仍未完成。

发布工具新增独立默认 Clang 差分、原样上游 lit、官方兼容证据及强制完整
兼容 gate。官方探针固定并校验原样源码；正例通过解析后尝试 O0/O2
编译、链接和执行；语言负例实际运行，未确认预期规则的失败不计验收。
没有改写上游库，也没有用 concept 适配库代表官方兼容。

当前证据和复现入口：

| 检查 | 证据与限制 |
| --- | --- |
| 默认 Clang 差分 | `clang-pristine-current.json`：11/11，与从保留官方源码独立构建的原版 Clang 22.1.2 比较，含 O0/O2 双向非平凡按值 ABI/异常清理；`build/clang-pristine/reference-identity.json` 记录逐文件源码、原始归档和二进制摘要。不是完整上游兼容证明 |
| 原样上游 lit | `clang-upstream-lit-current.json`：4/4，通过原 RUN 行；不是完整上游 suite |
| 插件 CTest | `ctest-current.log`：借用模式修复后的发布检查 24/24 |
| 原样官方正例 | `circle-current.json`：Circle stdlib 0/6、Safe C++ 0/14、头文件 0/4；输入和二进制摘要在探针前后稳定，未获得运行验收 |
| 官方语言负例 | 34 个输入实际执行；库/语法失败遮蔽预期规则，全部未确认规则 |
| 完整前端回归 | `frontend-current.log`：所有脚本及尾部 PCM 语义检查均已执行，唯一失败脚本为 `std2_consumers.py`（依赖类型 match 和未建模 leading where）。失败不再提前遮蔽后面的专项，门槛仍返回非零 |
| 发布检查 | `release-choice-borrow.json`：configure、两种构建、CTest、原版 Clang 差分、上游 lit、官方证据 gate 通过；native-tests 失败。子集未验证，完整兼容未建立 |
| 证明 | 局部 Lean/Z3 和执行检查不是 AST/CFG、PCM/ABI/CodeGen 精化证明；649 个 UB 候选条款仍未证明 |

新增 `proofs/safety-clause-map.json` 将 8 个固定 N4861 段落关联到静态拒绝、
动态检查、unsafe 契约及相关实现/测试；`ub_inventory.py --check` 检查段落
摘要和引用路径。8 项仍全部未证明，且没有把 649 项清单或规范覆盖缩小。
8 个官方 panic 负例在 O0/O2 各尝试构建，16 次均因库编译失败未运行，
不得计作运行时拒绝成功。

```sh
python3 tools/build_frontend.py --jobs 4
python3 tools/build_pristine_clang.py --jobs 2
python3 tests/lifetime_kind_constraints.py
python3 tests/forged_native_metadata.py
python3 tests/match_ranges.py
python3 tests/choice_borrow_patterns.py
python3 tests/dependent_match.py
python3 tools/clang_compatibility.py
python3 tools/clang_upstream_lit.py
python3 tools/circle_compatibility.py --output build/implementation-baseline/circle-final.json
python3 tools/compatibility_matrix.py
python3 tools/test_frontend.py
ctest --test-dir build --output-on-failure
python3 tests/verify_frontend_patch.py
python3 tools/release_check.py --report build/implementation-baseline/release-final.json
```

机器矩阵位于 `build/compatibility-safety-matrix.json`，绑定实际源码、补丁、
二进制和诊断摘要，明确 `inventory_complete=false`。标题索引仍仅供检索。
完整语言特性/库操作/安全性质映射尚未完成。

后续优先事项是依赖类型 match 的 AST/模板/PCM/CodeGen 保持性、原生
interface/impl/dyn 与关联类型/迭代、成员/表达式包和反射、记录生命周期
实参与泛型投影、调用点 static/outlives 和高阶方差、checked/legacy 拥有
参数 ABI、一般借用协程/非平凡 union/复杂静态与 TLS，以及检查器和 unsafe
运行库的程序级证明。Linux、Windows ABI、CUDA/device 仍待独立验证。

安全保证仅在 unsafe 实现满足契约、可信编译链及平台正确时适用于已建模
性质。任意错误 unsafe 实现仍可破坏安全性；属性、sanitizer 和局部定理
均不是整个编译器或程序无 UB 的证明。

### Compiler-owned choice identity (2026-10-13)

A default-mode annotation-shaped ordinary C++ record reproduced two payload
destructors versus one in pristine Clang. Native choice recognition now requires
the compiler-owned implicit record marker; source annotation strings describe no
native identity. The cumulative 89-file patch was rebuilt. The extended default
differential suite passes 13/13, and dependent-match plus choice-borrow PCM
ownership/exception tests pass O0/O2 ASan/UBSan. Evidence: `build/implementation-baseline/clang-choice-identity.json`,
`dependent-choice-identity.log`, and `borrow-choice-identity.log`.
The prior full run `release-deferred-match.json` failed only `std2_consumers.py`
in the independent script regressions; the leading lifetime-kind constraint remains
unmodeled. This does not establish production readiness or full Circle compatibility.

### Native panic checks and ordinary TU effects (2026-10-13)

Correcting the official death-test invocation exposed missing runtime checks:
`divide_zero.cxx` and `subscript_array.cxx` had compiled and exited normally at
O0/O2. The unmodified abort handler now compiles separately as default C++;
checked flags apply to the safety source only. Build failures are not panic proof.
Native CodeGen now branches to `abort()` before scalar integer division/remainder
by zero or signed minimum divided/reduced by -1, and before known-bound array
access/address formation. One-past address formation remains permitted; access
uses the strict bound. Floating operations, shifts, arbitrary pointer extents and
complete arithmetic safety remain outside this implemented scope.

An ordinary Circle TU's checked function effect was overwritten by an unsafe
classification when no named module owned it, skipping its body checks. Native
classification now preserves main-file checked effects, and lambda call operators
have independent checked classification. Header/global-fragment declarations
retain their conservative boundary; this does not establish complete plain-TU
library compatibility. Tests: `tests/native_panic_checks.py` passes PCM O0/O2 with and without
ASan/UBSan and four plain-TU boundary cases. Untouched official divide-zero and
array-subscript death tests now trigger the upstream abort handler at O0/O2
(four observed panics). Default Clang differential remains 13/13. Full release
evidence is being regenerated; remaining official sources still fail compilation.

### Unsafe module contract clarified (2026-10-13)

The user defines an unsafe module as traditional Clang: Circle syntax and safe
function declarations are unavailable there. A safe wrapper belongs in a safe
module and calls the legacy implementation inside an explicit unsafe block.
The abandoned proposal to support safe functions inside unsafe modules is not
implemented or claimed as a pending compatibility requirement.

Circle parser/lexer paths now require the checked dialect, and arithmetic/array
panic checks no longer attach to an ordinary unsafe-module function. Imported
checked function bodies retain checks through their function-type effects.
`tests/unsafe_legacy_mode.py` passes O0 source/IR comparison against independent
pristine Clang for contextual identifier names, scalar division/remainder,
arrays and nontrivial by-value objects. It also rejects Circle safe/choice syntax.
The 89-file patch replays without fuzz. These finite checks do not prove all
legacy language/ABI compatibility or all imported template execution paths.

The latest full run before this legacy-mode repair, `release-native-panic-checks.json`,
failed eight independent scripts: run, borrow_values, std2_consumers,
choice_patterns, relocation_operators, tuple_call, nested_borrows and
conditional_contracts. Known-bound subscripts and scalar integer division are
now dynamically checked rather than universally rejected. Several plain-TU
fixtures also relied on the former skipped body checks for unsafe calls/raw
pointer escapes/signed operations. Each expectation requires a targeted runtime
test or explicit implementation contract; no release candidate is validated.

Current priority: complete the requested Circle capabilities and original
library execution at O0. O2 expansion is secondary; type/lifetime/dispatch
semantics are not relaxed by selecting O0.

### Native interface declaration infrastructure (2026-10-13, O0)

Checked parsing now recognizes original `interface` declarations and unqualified
`typename item_type;` associated declarations. A compiler-owned interface marker
preserves the contract identity, while associated names are dependent qualified
types tied to that interface, not concrete typedef replacements or concepts.
The declarations and distinct associated names survive producer and importing
PCM serialization and O0 object generation in `tests/interface_declarations.py`.

This is declaration infrastructure, not complete interface semantics. Native
impl lookup/substitution, method matching, dispatch, dyn tables, inheritance
semantics, complete template specializations, defaults and associated-type
projection remain incomplete. Storage fields, direct object construction,
ordinary object inheritance, layout queries, default method bodies and calls
without impl lowering are rejected on the tested checked paths. Legacy import
and complete template paths are not established by these tests.

The untouched Safe C++ header's first error advanced from `interface` at line556
to `impl slice_iterator<T>: iterator` at line594. Official positive counts remain
0/14; this progression is not a compatibility pass. Evidence:
`build/implementation-baseline/circle-interface-declarations-current.json`.
Default Clang remains 13/13 in the finite differential, and the unsafe-module O0
IR/ABI comparison passes. Latest additional refusal checks are recorded in
`interface-declarations-final.log`; full release acceptance remains failed.

### 2026-10-13: interface 的隐式 Self（O0 声明基础）

原生 interface 现在隐式声明依赖类型 Self；显式 self 接收者使用该类型，而不是内部 interface record。tests/interface_declarations.py 验证不同 interface 的 Self 身份、Self 与关联类型的区别、接收者函数签名、作用域隔离和两个 PCM 的保存；重复声明 Self 稳定拒绝。这仍是声明基础，尚未实现 impl 的绑定、方法分派或 dyn。

当前证据为 build/implementation-baseline/circle-interface-self.json、clang-interface-self.json 和 compatibility-interface-self.json。原样 Safe C++ 正例仍为 0/14，Circle 库示例仍为 0/6；默认 Clang 有限差分 13/13 通过。unsafe legacy O0 专项、原生整数与数组 panic 的跨 PCM O0/O2 及 ASan/UBSan 专项通过。未重新运行完整发布验收，先前完整套件失败仍未全部关闭；不能据此宣称生产就绪。

### 2026-10-13: 原生 impl 声明绑定基础

解析原生 `impl type-id : interface-name`（包括 template-head），在 compiler-owned 实现记录中保留目标 Self 与 interface 契约类型。没有将其改写成 concept。tests/impl_declarations.py 验证目标别名、模板声明、O0 对象生成、PCM 保存与导入；非 interface 契约、存储字段和尚未实现的方法契约绑定明确拒绝。模板选择/偏序、重复实现一致性、关联类型替换、方法契约、分派和 dyn 仍未完成，声明成功不能算 impl 特性验收或官方库兼容。专项已纳入 tools/test_frontend.py。

### 2026-10-13: 具体 impl 的部分方法契约检查

为非依赖 impl 增加 interface Self/关联类型替换和方法参数、返回类型、安全效果、显式接收者匹配检查。原生 override 不再走普通 C++ 虚基类检查，而由该契约检查处理。专项包括正确签名（仍因执行路径未实现拒绝）与缺失关联类型、错误返回值、错误接收者反例。模板实现仍待实例化选择，完整 noexcept/生命周期/重载集合/重复实现一致性尚未验证；执行边界保持拒绝，不能视为方法分派完成。

上一版 impl-binding 的完整 tools/test_frontend.py 运行结果保存于 build/implementation-baseline/frontend-impl-binding.log：8 个脚本失败（run.py、borrow_values.py、std2_consumers.py、choice_patterns.py、relocation_operators.py、tuple_call.py、nested_borrows.py、conditional_contracts.py），新 interface/impl 专项通过。本次契约改动已构建并通过专项，但尚未完成新版完整发布验收。

### 2026-10-13: impl 方法的效果和 ABI 比较

具体实现的部分契约匹配进一步比较完整函数 ExtInfo（含安全效果与调用约定）、变参、参数 ABI 标记、返回借用来源和生命周期绑定/outlives 元数据；接口要求 noexcept 时实现必须满足。新增针对抛异常替代 noexcept 与 unsafe 替代 safe 的拒绝专项通过。元数据采用保守的相等检查，泛型替换、生命周期子类型及完整语义兼容仍未建立；不能当作全特性 impl 证明，运行分派仍拒绝。

ctest-impl-contract.log 的 24/24 结果来自此前已有插件二进制，不作为当前原生前端补丁验收；本次重新构建插件后需重新执行 CTest。官方 box_test 当前首个错误位于原样 std2.h 第 1580 行的 static kind where；解析推进过 impl 不表示头文件内部的安全效果与方法执行已完整检查。

### 2026-10-13: 具体 impl 重复定义检查

对具体目标/interface 组合按规范类型身份检查重复定义；类型别名不会产生独立实现身份。tests/impl_declarations.py 覆盖同 TU 重复、别名重复、导入 PCM 后在消费者重新定义的拒绝，并保留不同 interface 实现同一类型的正例。模板重叠/偏序、仅导入两个冲突 PCM 的全工程检查、跨对象链接的一致性和运行分派仍未实现。这是具体定义检查，不是完整 impl coherence 保证。

重建插件后的 CTest 24/24 结果在 build/implementation-baseline/ctest-impl-effects.log；当前新增前端定义检查尚需新版完整前端/发布验收。

### 2026-10-13: 命令选择安全模式

按用户要求，普通 TU 的检查不再依赖 #feature on safety；原样上游保留的该 directive 在 checked 命令下只作兼容语法，不选择模式。safe 命令检查非系统头文件的函数体，函数类型效果与分类一致；系统头仍保留既有 legacy 分类。tests/command_modes.py 覆盖无 directive、保留 directive、普通 TU 拒绝不受保护的指针访问、头文件函数体拒绝、safe wrapper 内显式 unsafe、O0 编译链接执行及 unsafe C17/C++17/20/23。现有 policy 参数与 PCM 协议没有改动。用户选择覆盖固定 Safe C++ 文档的按文件 directive 选择规则，不能将此差异隐藏为原样规范一致。

### 2026-10-13: 具体 impl 的显式接收者调用

已接入 `value.Interface::method(...)` 的具体实现查找与 Clang 显式对象参数调用路径。只有具体实现中通过 Self/关联类型、参数/返回类型、效果及 ABI 契约比较的方法获得 compiler-owned 许可标记；未知、依赖或未匹配方法继续拒绝。tests/impl_calls.py 验证 shared/mutable 接收者的同 TU 与跨 PCM O0/O2 编译、链接、运行，ASan/UBSan 通过；缺少实现、const 接收者可变调用、实现体内未经 unsafe 边界调用旧 C 函数分别因针对性规则拒绝。

模板实现选择、重载集合选择、隐式接收者、dyn、完整生命周期投影、拥有接收者异常路径与目标相关 ABI 尚未在这套专项验收。此进展不能等同完整 impl、官方安全库兼容或生产保证。普通 safe TU 现在读取现有 policy 来验证导入模块；未新增 PCM 格式/协议改造。此前 command-modes 完整前端回归仍有原 8 个脚本失败，新调用改动尚需新版完整验收。

### 2026-10-13: 原生 signed 算术运行检查

checked 函数的标量 signed 加、减、乘及复合赋值现在用 LLVM with.overflow intrinsic 计算定义良好的结果和溢出位，再进入已有 panic 路径；默认 Clang 和 unsafe 模块普通函数的 CodeGen 不进入该路径。未用 nsw 结果作为溢出判断依据。独立原版 Clang 默认模式差分 13/13 通过；这仍是有限回归证据。

tests/native_panic_checks.py 在跨 PCM、O0/O2、无 sanitizer 与 ASan/UBSan 下执行正常用例和 22 个 panic 用例，包括 signed 上下界、复合赋值、constexpr 与运行求值区别、除法以及标量/借用数组越界。tests/run.py 的原生模式 368 个编译用例与模块运行测试通过，tuple 调用 O0/O2 通过。编译器补丁在 pristine 源码上通过 --dry-run --fuzz=0 检查；本轮尚未进行实际新目录重放。相关摘要和日志位于 build/implementation-baseline/signed-arithmetic-evidence.json。

完整 Circle 兼容、模板 impl/dyn、signed 自增/自减与移位、完整发布验收仍未完成，不能以本专项通过声明生产或全特性完成。

### 2026-10-13: 模板 impl 的推导与实例化调用

已接入 Clang 模板参数推导，根据目标类型和 interface 类型实例化原生 impl 容器；实例化后的方法必须重新通过具体契约检查才能参与调用。compiler-owned 的容器和 Self/interface 绑定标记保持可信来源，未复制模板方法的执行许可。修复 BorrowValueTypeLoc 的 referent TypeLoc 链在模板替换时缺失导致的检查器崩溃；不是绕过检查器。

tests/impl_calls.py 现在用第一类借用验证具体实现、同一模板的两个实例、shared/mutable 接收者与 item_type=T 返回类型投影，涵盖同 TU/跨 PCM、O0/O2、无 sanitizer 和 ASan/UBSan；错误实例契约、歧义模板、const 变更以及模板体中未经 unsafe 调用旧 C 函数均拒绝。native_borrows 的 21 个反例及 dependent_match 回归通过；默认 Clang 有限差分 13/13 通过。编译器/源码摘要与日志在 build/implementation-baseline/generic-impl-evidence.json。

模板 impl 已不再仅解析声明，但完整模板优先级、约束候选筛选、默认参数、方法重载、dyn、拥有接收者异常/ABI 与跨模块完整 coherence 未完成。新版官方探针仍为 Safe C++ 正例 0/14、Circle 库示例 0/6；不能宣称全线 impl 或原样库兼容。上一版本完整回归剩 std2_consumers.py、relocation_operators.py、nested_borrows.py 三个失败，新模板实现尚需完整回归与发布 gate。

### 2026-10-13: impl 约束筛选与末尾默认参数

不满足 requires 的模板候选现在按 SFINAE 排除，不再阻止另一个有效实现的调用；具体实例的契约检查仍不能被 SFINAE 隐藏。推导后末尾未确定的参数交给 Clang 的模板默认参数替换，tests/impl_selection.py 包含 U=T 的依赖默认值。用不同约束选择 char/unsigned 两个实现，在同 TU/跨 PCM、O0/O2、无 sanitizer/ASan/UBSan 下实际执行通过；没有可用候选的调用拒绝。现有 impl_calls 回归通过。累计补丁实际无 fuzz 重放，89 个文件与当前 manifest 匹配。摘要与日志在 build/implementation-baseline/impl-constraint-evidence.json。

完整模板排序、交叠 coherence、中间未推导参数、方法重载与 dyn 仍未完成。本轮之前的完整前端回归仍有 std2_consumers.py、relocation_operators.py、nested_borrows.py 三个失败，不能报告完整通过或完整 impl 支持。

### 2026-10-13: impl 的部分排序与约束 subsumption

impl 候选现在统一收集，先推导和筛选，再按固定 Circle 文档所述的 (target, interface) 主模板部分专门化语义排序；查询节点只用于调用 Clang 的既有部分排序/约束 subsumption 引擎，不成为用户类型、输出符号或 PCM 实体。具体实现优先于泛型，最终赢家必须优于所有其余候选。只对选中实现执行实例化及契约检查，避免未选中泛型体污染具体实现。

tests/impl_selection.py 已执行具体 > 部分 > 泛型、跨命名空间、两种声明顺序、概念约束 subsumption、未选中泛型体不实例化、生产者已实例化后通过 PCM 导入以及不可比较候选歧义拒绝。在 O0/O2、无 sanitizer/ASan/UBSan 下通过；原 impl_calls 通过，默认 Clang 差分 13/13，通过原始文件实际无 fuzz 重放并匹配全部 89 个补丁文件。摘要见 build/implementation-baseline/impl-order-evidence.json。

这些专项不能证明完整 impl；跨模块完整 coherence、重载、dyn、复杂生命周期投影、拥有接收者异常/ABI 与官方原样库端到端仍开放。当前完整前端/发布 gate 未全部通过。

### 2026-10-13: 方法重载与借用返回/推导更新

普通 impl 参数及 shared/mutable 接收者重载已通过 impl_overloads.py 的同 TU/PCM、O0/O2、ASan/UBSan 执行专项；此前段落中的重载未完成是历史状态，方法模板仍开放。原生借用隐式返回现在执行 affine 转移，borrow_values.py 新增运行和拒绝用例，本轮 29 个反例与 O0/O2 PCM sanitizer 验收通过。

借用模板推导现在传播调用推导的 referent qualification 许可。可变借用匹配 const T^ 能推导 T，但后续 mutable-to-shared 重借用转换仍拒绝，不能算该调用已支持。原样 box_test 继续失败：static/where、标量隐式借用、重借用、optional niche 布局及 phantom 初始化仍开放。当前证据及源码/二进制摘要见 build/implementation-baseline/borrow-deduction-evidence.json；未运行本轮完整前端/发布验收，未达官方整库兼容。

### 2026-10-13: 临时借用 qualification 与当前完整回归

临时可变借用可转换为同 referent 的共享借用，AST 使用 qualification/CK_NoOp 保留来源；具名可变借用转换仍受限制。borrow_values.py 在 O0/O2、PCM、ASan/UBSan 下执行通过，30 个反例包含共享返回借用存活时写原对象的拒绝。impl_overloads 回归及默认 Clang 13/13 有限差分通过；89 文件累计补丁实际无 fuzz 重放并匹配 manifest。

当前完整 test_frontend 仍失败于 std2_consumers、relocation_operators、nested_borrows。relocation 测试的 printf/全局计数观察已按产品规则置于显式 unsafe，match 保持 checked，输出断言未改；移出后状态误报仍导致失败，没有将其计为通过。原样 box_test 尚未编译成功，本轮官方运行验收增加 0；static/where、标量隐式借用、布局与初始化仍需实施。证据见 build/implementation-baseline/borrow-qualification-evidence.json 和 baseline-failure-classification.json。

### 2026-10-13: match 移出生命周期与父借用修复

拥有型 subject 移出后不再写已结束生命周期的原 choice tag；借用解引用/arrow 路径保留原对象，在原地移出 payload 并清空活动 tag。FlowAnalysis 识别 native borrow 解引用内部指针 cast，并将直接父借用纳入引用绑定的 parent 集合，继续保留其他别名冲突检查。

choice_match 新增拥有堆内存 payload 的本地 owning match，只析构一次断言；原有 borrowed match、异常析构与 6 个反例保持，O0/O2 ASan/UBSan 通过。relocation_operators 保持原输出断言，O0/O2 无 sanitizer/ASan/UBSan 通过；choice_borrow_patterns 与 borrow_values 专项通过。89 文件补丁实际无 fuzz 重放。当前源码/二进制证据见 build/implementation-baseline/match-source-tag-evidence.json；最新完整回归之前有 3 个失败，本次只确认 relocation 专项已修复，未声称全量通过。官方运行验收本轮增加 0，原样 box_test 仍待继续实施。

### 2026-10-13: 共享标量参数隐式借用绑定

const T^ 参数可以从同 referent 类型的标量/枚举实参形成共享借用；PRValue 物化到调用所在 full-expression，lvalue 保留对象来源。模板推导和推导后类型验证保持一致。borrow_values 的 O0/O2 PCM ASan/UBSan 执行与 32 个反例通过，临时整数借用逃逸因 provenance 拒绝。impl 重载专项及默认 Clang 有限差分 13/13 通过；89 文件补丁实际无 fuzz 重放。

原样 box_test 三处 assert_eq 标量绑定错误关闭，仍有 static/where、嵌套 box、optional niche、borrowed scalar read 与 phantom 初始化阻塞。当前官方探针 Safe C++ 语法 1/14、Circle stdlib 0/6；ptr2 在当前二进制 O0 编译链接运行退出 0，但 main 为空且不使用 std2.h，不能代表官方安全库跑通。规范 P3390R0 的 Destructors and phantom data 段明确 __phantom_data 不影响布局/初始化，本仓库普通字段实现尚需修复。源码/二进制与日志绑定见 build/implementation-baseline/scalar-borrow-evidence.json；本轮没有声称完整回归或发布通过。

### 2026-10-13: phantom 非存储语义与 const 接收者安全漏检

`__phantom_data` 使用 compiler-owned 隐式标记保留字段类型/生命周期信息，
但在 macOS arm64 的记录布局、CodeGen 存储、隐式初始化、复制/赋值和析构
路径中不形成物理子对象。默认特殊成员删除检查不再要求 phantom 类型具有
可访问的构造/析构器；checked 构造器的标量初始化检查也排除此非存储字段。
显式初始化、成员存储访问及伪造 native 标记均拒绝。聚合初始化索引及
constexpr phantom 子对象仍未建模，聚合初始化明确拒绝；并非完整 phantom
兼容。借用检查器仍遍历 phantom 字段，未删除其类型/生命周期责任。
AST 格式由 45 升至 46，旧 PCM 必须重建。

`tests/phantom_data.py` 已通过 O0 同 TU/PCM、无 sanitizer 和 ASan/UBSan：
高对齐 phantom 不影响布局，已删除的 phantom 构造/复制/析构器不参与
物理对象操作，普通及异常清理没有 phantom 构造/析构副作用；显式操作、
伪造标记及无来源借用反例拒绝。关闭扩展后保留普通同名字段及源 annotation。
这些专项不是完整生命周期/drop 检查或无 UB 证明。

完整前端检查发现显式接收者降级可把 `const V^` 制造成 `V^`：生成借用
只比较 unqualified 类型并直接使用目标类型。现在生成借用及 operator->
回退路径保留 cv 限制，不允许丢弃 const/volatile；impl_calls 的 const
反例保留拒绝断言，改为检查具体的不可转换诊断，并新增 const 对象和跨
PCM 拒绝用例。同 TU/PCM、O0/O2、ASan/UBSan 的正反例通过。
另修复共享 FlowAnalysis 误用原版头文件不存在的 isSafetyBorrow()，仅
原生构建使用该分支；生产借用域 10368 项检查通过，未删失败测试。

原样 box_test 的 phantom 初始化诊断消失，box<int> 从 16 字节变为 8，
optional<box<int>> 仍为 16，未达 niche 布局断言。当前还失败于原样
std2.h:1580 static kind where、box_test:27 嵌套 box 解引用、:32 niche
布局及 :38 借用标量读取。O0 编译仍失败，尚无 box 官方运行结果。
最终官方集合探针仍 1/14 语法接受（空 ptr2），Circle stdlib 0/6；不能
报告原样安全库跑通。默认 Clang 有限差分仍 13/13。

证据入口：phantom-test-final.log、phantom-receiver-impl.log、
phantom-borrow-domain.log、clang-phantom-receiver.json、
circle-phantom-receiver-final.json、official-box-phantom-final.log 和
phantom-receiver-patch.log（92 个文件从原始源码实际无 fuzz 重放）。
新版完整前端日志 frontend-phantom-receiver-final.log 保留原始失败结果；
impl_calls 中过时诊断预期由上述独立重新执行验证修复，未改写日志。
完整发布、完整兼容、phantom 聚合/constexpr 和动态能力仍未完成。

本轮最终完整前端命令返回非零：原始日志列 impl_calls、std2_consumers、
nested_borrows 三项失败。impl_calls 在校正精确诊断后同一二进制独立
重跑通过；仍开放的实际脚本为 std2_consumers 和 nested_borrows。
没有将局部重跑描述成完整 gate 通过。phantom-receiver-evidence.json
绑定最终源码、二进制、运行库、官方输入摘要与上述记录。

### 2026-10-14: 运算符 borrow 投影与原生 mutable context

固定 Safe C++ P3390R0 明确区分运算符调用的自动 borrow 解引用与普通
命名函数调用返回的 handle。原生 `operator*` 现在将返回的 BorrowValue
投影为 referent lvalue；普通 `obj.operator*()` 保留 borrow 类型。模板
重建内部 handle 调用时抑制重复投影，避免多解引用一层。
`tests/operator_borrow_projection.py` 的嵌套拥有者、模板和 PCM 在 O0/O2、
无 sanitizer 和 ASan/UBSan 下实际执行通过；普通函数 handle 到标量的
隐式转换仍拒绝，const 写入、局部/临时拥有者借用逃逸与活跃共享别名写入仍拒绝；临时拥有者在同一 full-expression 内的读取通过。
本轮仅补 unary operator*；其余运算符的完整投影还需沿官方失败推进。

此前 parser 将 mut 作为空操作。现在 high-precedence mut 表达式保留
compiler-owned AST 标记，并通过模板重建、AST importer、PCM 保持。
在第一类 borrow 模型中，默认 receiver 选择共享重载，显式 mut 允许
可变 receiver 和同类型标量/枚举 lvalue 的可变 borrow 绑定。不会从
const/volatile referent 丢弃限定符，也不会借此复制具名独占 handle。
函数参数、下标表达式、普通括号中的低优先级表达式与 lambda 函数体
不继承外层 mutable context；重载的 unevaluated 语义上下文保留调用点
的选择意图。依赖 unary dereference 在实例化时判断是否 raw pointer，
实例化后的 raw pointer 仍拒绝，不跳过模板实例的安全检查。

`tests/mutable_context.py` 验证共享/可变选择、mut *cell 的 borrow 绑定、
泛型和模板内非依赖调用、PCM、O0/O2 与 ASan/UBSan，以及 const、别名、
缺少 mut、函数参数、普通括号、lambda 边界和 raw pointer 实例化反例。
borrow_values、impl_calls、impl_overloads、native_self 专项通过。
choice_match 的 value()/forget() 确实移出/销毁载荷，旧夹具调用缺少 mut；
仅为这些操作补 mut，保留全部输出、析构计数和拒绝断言，重跑通过。
没有改动官方源码。这不是全领域 mutable context/legacy reference
规则或完整运算符模型已实现的声明。

AST 格式由 46 更新至 47。旧 PCM 用上一版实际二进制生成并保存其
二进制/运行库/输入摘要，新二进制导入时明确报 older format，见
old-mutable-pcm/{identity.json,rejection.log}。93 文件累计补丁从原始
Clang 22.1.2 源码实际无 fuzz 重放，当前源码与 manifest 匹配。

原样 box_test:27 的嵌套 **p、:38 的 match 标量读取，以及 :19 的
int^ x = mut *p 现在不再报错。当前 O0 仍因 std2.h:1580 static kind
where 与 box_test:32 optional niche 布局失败（16 == 8）；没有链接或
运行成功，且语法错误仍会遮蔽完整库体的安全验收。官方集合仍 1/14
语法接受（空 ptr2），Circle stdlib 0/6；不能当作库端到端通过。
默认 Clang 有限差分仍为 13/13。

当前完整 frontend-mutable-context-final.log 命令非零，原始记录为
choice_match、std2_consumers、nested_borrows 三项失败；choice_match
经上述正确显式 mut 夹具独立重跑通过，尚未报告整条 gate 通过。
实际未关闭的脚本仍为 std2_consumers 与 nested_borrows。证据与最终
源码/二进制/运行库摘要见 mutable-context-evidence.json；完整发布、
完整生命周期与 Circle 兼容仍未达成，sanitizer 不是全编译器无 UB 证明。

### 2026-10-14 — 关闭共享 slice、嵌套句柄及双 PCM ABI 回归

本轮沿上一版失败的 nested_borrows 继续，未重新全仓库审计。
旧夹具在 checked main 中从裸指针构造未知来源的 slice borrow、直接
调用 printf，并用可变借用访问只读句柄；这些应服从现有安全规则。
现将裸指针入口放入独立的显式 unsafe main；句柄复制、rel、嵌套借用、
共享读取和可变元素写入由独立 safe 函数检查，printf/裸地址返回使用
显式 unsafe 边界。原先的两行输出断言全部保留，另增加 7 9 写入结果。
官方源码、特性宏和契约未改动，也没有关闭检查。

修复三个实际编译器问题：
- src/SafetyContracts.h 的 objectBorrowImpl 现在使用编译器已有的
  circleBorrowIsShared 分类识别 const slice 元素；不能以生成双字记录
  自身缺少 const 为由把 const [T; dyn]^ 判为可变借用。嵌套记录的
  独占生命周期仍递归检查，活跃可变别名冲突仍拒绝。
- ASTContext::getBorrowValueType 不再透过 borrow handle 去规范化
  slice 元素，保留 ^const handle 所借句柄存储的 const。slice 记录
  规范化保留其他存储限定符。
- getCircleSliceType 恢复导入记录的缓存；getBorrowValueType 统一
  独立模块生成的内建 slice 记录，生成记录设为 Unowned，以避免类型
  相同而模块前缀不同的参数 ABI 名称。用户函数仍拥有其命名模块。
  首次双 PCM 类型失败和链接失败都是真实重现，未通过改写源码绕过。

tests/nested_borrows.py 在本地与两个独立 PCM、两种导入顺序、O0/O2、
普通与 ASan/UBSan 下编译、链接、运行，精确输出为 2 2 2 2 / 1 1 /
7 9。16 个本地/PCM 反例拒绝 const 元素写入、const 句柄重绑、活跃
可变别名、移后使用、缺失 unsafe、嵌套 lambda 越权和未知裸指针
借用来源。保留的 O0 普通与 sanitizer 可执行文件、源码和实际运行
记录在 build/implementation-baseline/nested-borrow-o0*；实际动态
依赖单独记录，不能把运行库快照中存在的文件都视作链接依赖。

AST 格式最终由 47 升到 49。旧 47 PCM 和修复前实验版 48 双 PCM
均由实际旧二进制生成，保存摘要，最终二进制明确报 older format，
见 old-slice-pcm 与 two-slice-pcm 下的 identity/rejection-v49.log。
中间版本记录保留；最终结论只绑定最终源码和二进制。累计 93 文件
补丁在原始 Clang 22.1.2 上实际无 fuzz 重放并逐文件匹配。

最终 frontend-slice-v49-final.log 非零，唯一失败为 std2_consumers.py；
choice_match 与 nested_borrows 已在完整 gate 中通过，其他专项也完成。
默认 Clang 有限差分 13/13。不能称完整发布检查已通过。
原样官方 box_test 在最终二进制 O0 下仍因 std2.h:1580 static kind
where 与 box_test:32 optional niche 布局失败（16 != 8），尚未链接或
运行；官方集合仍 1/14 语法接受（空 ptr2），Circle stdlib 0/6。
下一实际阻塞是 static 生命周期 kind 的类型/借用投影、函数类型契约、
模板替换和直接/间接调用检查，不能仅放行 where 解析来消除报错。

最终源码、manifest、补丁、driver/libclang-cpp、运行库快照、实际动态
依赖、固定上游输入、运行结果及日志摘要见 slice-evidence.json。
固定 Circle/Safe C++/mdspan 引用树仍 clean。完整生命周期、niche、
官方库端到端、完整 Circle 和最终发布验收仍未完成，goal 保持 active。
有限差分、sanitizer 与局部证明不是整个编译器无 UB 的证明。

### Static kind contracts and official box layout blocker (2026-10-14, AST 50)

本轮沿原样 std2.h:1580 的 `where F: static, Args...: static` 实现
static kind 契约，不再因该声明拒绝整个头文件。支持直接类型参数及包的
carried lifetime、命名借用 region、result-only static region。参数函数类型
元数据保留这两种不同承诺；按值对象和借用 handle 的自身栈存储不会因
T:static 变成永久。非 static kind、未表示的类型参数、复合类型投影、同一
类型参数的未建模间接出现及外层 class receiver 明确拒绝；不是完整
Circle 生命周期 kind 实现。

调用点验证永久且非 TLS 的来源。未知 extern 借用全局不能作为永久来源。
checked、unsafe 函数、显式 unsafe block、command-unsafe module、构造器、
模板/包、间接调用和全局初始化均保留契约检查。禁止隐式转换或显式 cast
擦除 static 契约；safe 和 unsafe 虚函数覆盖均不能改变这些前置条件。
函数类型 ExtParameterInfo 扩到16位，ABI参数分类低位保持原义；AST版本
49 -> 50，保存的真实49 PCM在50上报告older format，拒绝日志已保留。

同时修复借用聚合体 relocation 的效果：平凡搬移 readonly 借用 holder
只改其存储，不写 referent；live storage borrow 仍阻止搬移。非平凡
构造保留原来的保守效果。lifetime_kind_constraints.py 在 O0/O2、PCM、
普通及 ASan/UBSan 下通过；56个 local/PCM反例、3个command-unsafe反例
及8个未建模签名拒绝全部通过。原始失败日志保留，未降低断言。

最终 frontend-static-v50-final.log 返回1，唯一失败 std2_consumers.py。
该适配库/consumer 仍有 mutable receiver 调用缺少 mut 的转换错误，以及
老式双重解引用；不计为官方兼容证据，也未改官方源码获取通过。
默认 Clang 有限差分13/13；pristine LLVM22.1.2 的93文件补丁实际无fuzz
重放通过。sanitizer/这些有限测试不证明整个编译器无UB。

重新检查全部固定官方程序：1/14正例在O0/O2编译链接执行成功，即原样
ptr2.cxx。另保留O0/O2普通及ASan/UBSan四个可执行文件，exit0、输出为空。
该程序main为空，仅验证native借用函数指针类型和模板初始化，不能据此
声称官方安全库操作/生命周期/析构已端到端通过。box_test现在只剩:32
optional<box<int>> niche布局断言16!=8，没有实际执行。niche_zero仅有属性
记录，choice仍生成独立tag+union payload；最小复现niche-zero-repro.cxx
和失败日志保留。下一实际阻塞是把零niche同时接入布局、构造、判别和析构，
不能仅改sizeof或移除断言。

官方负例仍逐个保留实际失败。无关语法/类型错误不计安全验收。
unsafe/unsafe_function.cxx在当前command-safe TU中接受：其无safe/unsafe
后缀的main-file `int f();`被现有ordinary-TU命令模式规则归为checked。
上游该负例将该声明归为unsafe；这是待核对的语义差异，未计预期拒绝，
不能宣称全部官方安全负例通过。用户明确要求#feature不切换模式，必须
在该规则下独立解决外部声明契约分类，不能靠#feature恢复旧模式。

证据绑定当前实际source/binary/runtime：static-kind-evidence.json；
libclang-cpp SHA256 d4dd162a1580366005c43ee84bf66bb419ad56ee79cc964a332c7afab7ae0fb2；
patch SHA256 9db569149bce55c7191b798b73add55eca87d77615039a94be70f2db5d20bfdf。
三个固定上游引用树clean。完整Circle、14/14官方库、niche及最终发布门槛
仍未达到，goal保持active。

### External declaration boundary and borrowed-arrow template crash (2026-10-14, AST 51)

本轮关闭上一节记录的裸外部声明安全分类问题。ordinary command-safe TU
的无函数体、无显式safe效果声明不再自动获得checked函数类型；
`int f();` 保持unsafe，显式safe声明、已匹配的同型checked重声明及
safe命名模块声明仍携带契约。继承此前声明时比较完整函数类型，不能
因同名safe重载给另一裸声明授予safe分类。定义依旧按命令模式检查，
#feature不改变模式。该修复在Sema建立函数类型时完成，推导出的函数
指针也保持unsafe，不能仅靠直接call诊断绕过。ordinary未明确safe的
forward declaration之后再写自动checked定义，须遵守效果重声明一致性；
不能默许外部未检查实现。完整模板/外部契约互操作仍需推进。

tests/command_modes.py覆盖直接调用、auto函数指针、转为checked指针、
同名不同形参重载、显式unsafe调用、显式safe声明/定义和按值标量ABI。
分别编译checked provider及传统C++ legacy实现；safe wrapper在unsafe块
内调用legacy但对外仍safe。O0/O2普通及ASan/UBSan四组链接执行通过。
原样官方unsafe/unsafe_function.cxx现在仅因调用unsafe f被拒绝，明确
验收该边界；external-contract-official-oracle.json保留源码哈希、真实命令
及诊断。上一节accepted记录是历史状态，不是当前结果。

官方负例探针还发现此前AST50已有的mutex1/mutex2崩溃，本轮优先关闭。
已将其缩成borrow-arrow-template-repro.cpp，before日志为exit139，after
正常编译。根因：模板中非依赖的operator->已经存有转换后的self借用
作为arg0，TreeTransform重建调用时将handle当record传入，release模式
castAsRecordDecl得到null后崩溃。BuildOverloadedArrowExpr现在先投影借用
回对象，再重新选择operator->。新ArrowWrapper读取41的实际运行检查
加入operator_borrow_projection.py，local/PCM O0/O2普通及ASan/UBSan通过；
原有const、生命周期及alias拒绝断言保留并通过。

AST版本50 -> 51，使旧PCM自动推断的外部safe效果失效。保留真实历史
50 PCM并实际确认51报告older format。该50 PCM的精确producer二进制
未保留，identity明确标注仅有历史轮次快照，不能声称匹配；本轮当前
编译、回归和官方探针绑定实际源码/二进制。前一节49 PCM精确绑定证据
仍保留。此借用箭头修复不增加新的metadata格式。

最终frontend-external-arrow-v51-final.log退出1，唯一失败仍是
std2_consumers.py；新增command/arrow检查都已在该最终gate执行。
默认Clang有限差分13/13，93文件pristine22.1.2补丁无fuzz重放通过。
重新检查全部固定官方输入，negative集合不再有编译器崩溃。
mutex1/mutex2仍因更早的int->mutex构造转换错误拒绝，不计预期
生命周期负例通过。原样box_test仍只有:32 niche布局16!=8断言，
尚未链接运行。正例仍仅1/14 ptr2空main运行；不代表官方库操作成功。

证据external-arrow-evidence.json；实际libclang-cpp SHA256
717a41a40a9ce042937b6c617d0bcc631b8abe8d4f0e058475438e92174b6e59；
patch SHA256 b63d7d5ff4f19a25a4bf549eb5a01b0ae7c52efe59cbab10182bc615f806f41b。
官方引用树仍clean；没有改官方源码、特性宏、契约或断言获取通过。
下一个实际官方正例阻塞仍是box optional的零niche表示，须同时实现
布局、构造、match、move/drop判别及清理；当前goal保持active。

### Pointer zero niche, virtual choice tag and drop cleanup (2026-10-14, AST 52)

原样box_test的optional<box<int>>布局断言现在通过：受信任的
[[safety::niche_zero]]单物理指针payload与一个void备选的native choice
共用指针表示，sizeof为8。CircleNiche.h由实际完整定义及选中的模板
pattern推导描述符；只接受编译器生成的implicit标记。用户annotate不能
伪造，未带标记的偏特化不会继承primary的布局承诺，多字段payload仍用
传统tag。本轮没有把任意零字节表示认定为通用niche。

布局、ABI空字段分类和CodeGen统一跳过虚拟tag；读tag由指针是否null
推导，设置empty/moved/drop清空指针，设置some保留待初始化payload。
.some(null)必须panic，包括显式unsafe块和全局常量折叠路径；不能静默
变为none。常量初始化器遇到无效some返回动态初始化路径并执行检查。
choice要求完整payload前先请求实例化，修复模板具体类型被提前判为
不完整的问题。官方atomic relocation模板实例化也保留原来implicit
标记的可信性，不能把编译器metadata误判为用户伪造。

borrowed drp只求值目标一次，正常及EH清理都在payload析构之后清空
实际目标tag；析构抛异常时外层owner不会再释放payload。原来的借用
操作数AST重复求值被删除。补充反例还发现经返回借用调用执行drop后
仍能读取原owner：Flow现在对choice保守退休所有契约可能来源；生命周期
契约不等于对象身份。普通record经未知身份的调用结果drop明确拒绝，
避免owner自动清理再次析构。没有将不精确的来源直接用作CodeGen地址。

niche_zero.py涵盖两种备选顺序、default/some匹配、relocation、owned
及borrowed drop、求值次数、精确析构与抛异常析构、模板/偏特化/伪造
标记、local/PCM O0/O2普通和ASan/UBSan。8次正例执行、24个安全拒绝
及8次local/global null payload SIGABRT通过。native_replacement及
choice_match原有运行和拒绝断言也通过。这是局部验证，非整个编译器
无UB的证明。

AST51 -> 52使旧物理tag布局PCM失效；本轮之前实际生成的51 PCM及精确
producer/source/binary摘要保存在old-niche-pcm/identity.json，52实际
报older format。新增header进入补丁及manifest，verify_frontend_patch
现在从+++路径识别新增文件，pristine22.1.2的96文件无fuzz重放通过。
默认Clang有限差分13/13，三个固定上游引用树保持clean。

原样官方O0编译链接尝试仍退出1，尚未产生box_test可执行文件；现在
实际阻塞前进到std2.h的string_constant::text /static返回契约、raw
slice factory的安全分类、source_location隐式special member等。
static-result-unquantified.cpp保留无需整个官方头文件的最小复现。
固定draft明确无safe后缀函数默认为unsafe；当前ordinary definition
自动safe分类尚未修正，不得把此差异描述为Circle兼容。上游允许unsafe
qualified构造在safe context直接调用，与用户要求所有safe->unsafe
调用必须显式unsafe块不同；后续仍遵守用户更严格规则并记录差异。
原样正例仍仅1/14 ptr2空main，不代表官方安全库操作通过。

本轮绑定证据niche-evidence.json；实际libclang-cpp SHA256
caec3899a99fe6e0c3a093d8bc909ea6e367afe49db53975501cd6d9df828cbe；
patch SHA256 5c6435defd95d91b80cc65b96a9d4b2b9fe177680f298dd2a0d367666f2d79c1。
完整Circle、官方14/14和最终发布验收尚未达到，goal保持active。

最终frontend-niche-v52-current.log退出1，唯一失败脚本仍为
std2_consumers.py；新增niche和返回借用drop反例均已在最终gate执行。
官方探针和所有当前证据的source/binary/runtime摘要重新核对稳定。

## 2026-10-14：AST53 静态结果/字段契约与官方头文件效果阻塞

接续AST52的string_constant::text实际失败，支持显式结果/static、显式
参数/static及静态字段的可信metadata。内建/static与结果-only
/(where L:static)函数结果类型规范化；无static约束的结果-only binder
保留不同的类型身份，不能据此声称其generative生命周期已实现。旧的
无输入结果region近似仍使用static来源；官方raw slice factory /(a)
因此明确失败，不能忽略契约或把任意raw地址伪装成permanent来源。

静态结果体、参数传递和字段初始化/赋值在unsafe函数及unsafe块中仍检查
来源。拒绝local、TLS、未知借用和擦除/创造static函数指针契约。允许
永久来源满足较短的native量化结果region；传统C++ reference annotation
规则保留。静态字段通过constructor/aggregate/template/PCM投影不依赖
局部holder的生命周期；这不是完整的类生命周期投影实现。字段模板
实例化保留compiler-implicit标记，表示cast、缺失字段初始化及未知
raw来源明确拒绝。固定slice只识别同元素/不去const的已知数组或字面量
和在allocation范围内的常量长度，动态raw slice预条件尚未建模。

最小复现另外发现两处安全漏检并修复：未知具体来源的/static借用必须
与任意可能的全局写入冲突；全局pointer变量的存储期不能证明其指向
对象的永久生命周期。字符串字面量单独使用只读来源。收紧来源检查
一度影响match、replacement、phantom和传统分析fixture，已恢复显式
owner、native借用、隐式this及传统C++路径，保留新安全反例。独立
borrow-domain fixture的两个条件编译回归也修复，10368检查通过。

普通TU隐式trivial构造/析构可推导safe效果，递归尊重子对象的unsafe
操作、volatile、模块模式和affine copy限制，未把用户函数体自动视为
已验证的安全库。固定draft允许safe函数返回raw pointer value，native
返回现按该语义支持，raw解引用仍要求unsafe。传统extension规则保持。
noreturn正常退出改用不含EH边的CFG，修复throwing legacy provider误判。
模板实例化的noreturn仍有另一路径失败：noreturn-template-v53.cpp与
官方panic_impl同样报normal completion，最小复现与诊断已保存，不能
把非模板修复描述为官方panic已通过。

static_results/static_fields/native_effect_paths在local/PCM、O0/O2普通
及ASan/UBSan共24次正例执行和320次拒绝检查通过。包含linked传统C++
provider、导入后首次模板实例化、已知全局写入、raw pointer来源伪造及
noreturn正常返回反例。已有生命周期kind约束和choice/niche等完整gate
运行通过；最终frontend-static-v53-final.log退出1，唯一失败脚本为
std2_consumers.py。测试与sanitizer是局部证据，不是编译器无UB证明。

原样box_test O0编译链接尝试仍退出1，无可执行文件。已消除text getter
/static、source_location/string_constant隐式trivial special member、
字面量临时borrow以及raw pointer返回错误。实际剩余错误位于std2.h
68的generative raw slice factory、168的模板noreturn、380的类region
结果投影以及335/264的初始化/作用域来源。官方集合仍1/14（ptr2空main），
不代表真实安全库操作通过；其余负例的不相关语法失败不计安全验收。

AST52 -> 53使旧契约/效果PCM失效。old-static-result-pcm/identity.json
保存真实52 producer，最终53 reader报older format。补丁96文件在
pristine22.1.2无fuzz重放通过；默认Clang有限差分13/13；三个固定上游
树clean。static-evidence.json绑定当前源码、clang、libclang-cpp、
ASan/UBSan运行库、官方探针及最终日志，旧52证据不改写为53结果。

原有ordinary/named-module未标记函数自动safe默认仍不同于固定Circle
默认unsafe，未修正，不能声称兼容。上游unsafe-qualified构造的调用
豁免与用户要求有差异，继续遵守用户更严格的显式unsafe块规则。
完整14/14、完整Circle和最终发布验收均未达到，goal保持active。

## 2026-10-14：AST55 unsafe 边界的控制流与生命周期

上一轮是源码和实际二进制绑定的进展，本轮接续noreturn-template-v53
而非重复全仓库审计。AST对比确认：ParseUnsafeStatement原先用可变
bool条件变量的恒真if表示unsafe，模板TransformIfStmt将条件重建为
变量读取，CFG遂产生跳过整个unsafe块的假分支。AST54中间构建先把
compiler-implicit条件改成const bool，实际模板noreturn错误消失。
随后执行正例发现unsafe body仍被当成词法scope：变量在块尾提前结束
生命周期，CodeGen也会提前析构；仅消除CFG假分支不能修复这个问题。

最终AST55用CircleSafety.h识别编译器生成的const/implicit/true边界。
CodeGen不为该边界建立cleanup scope；CFG在外层compound登记其中
声明，直接访问边界body；用作普通控制流子语句时仍建立控制流所需的
隐式scope。Flow的scope映射同样透明，unsafe权限仍按原边界记录，
lambda和嵌套方法独立检查。不是把unsafe body略过分析或跳过析构。

native_effect_paths在local/PCM O0/O2、普通及ASan/UBSan共8次执行和
64次拒绝检查通过。导入后首次模板实例化验证：声明可在unsafe后使用，
对象在外层正常结束、异常退出、普通if子语句结束时精确析构一次；
模板noreturn调用throwing legacy provider可异常退出；模板实际
fallthrough、lambda和嵌套safe方法直接调用unsafe仍拒绝。
unsafe-enclosing-scope-v55另证实：外层普通块结束后使用借用仍报
borrow outlives its owner。这些局部测试不构成编译器无UB证明。

原样box_test实际O0编译链接尝试仍退出1，没有可执行文件；std2.h
168模板panic_impl noreturn以及335/264初始化/作用域错误已经消失。
当前真实错误前进到68的generative raw slice factory以及380/394等
类生命周期结果投影。class-region-projection-v55.cpp把后者缩成
Holder/(a)::get(self)：类field region尚未进入函数结果契约。owning
self的存储期不等于字段所借对象的存储期；不能把所有字段来源混为
一个region来允许结果投影，更不能假装static。此复现保留为未实现
功能，不把不相关的missing-contract错误计作安全反例通过。

最终frontend-unsafe-scope-v55-final.log退出1，唯一失败脚本仍为
std2_consumers.py；其它已支持回归通过。static results/fields/effect
fixtures合计24次执行及344次拒绝检查。默认Clang差分13/13，三个
固定上游树clean。官方集合仍1/14，仅ptr2空main；真实安全库操作、
14/14及完整Circle目标尚未达到，原有函数效果默认差异也仍保留。

补丁核对发现新CircleSafety.h遗漏manifest，已加入并重新生成；最终
97个pristine22.1.2文件无fuzz重放通过。重新构建后动态库摘要发生
变化，最终gate、默认差分、官方探针均在最终二进制重新运行并绑定。
实际AST53 producer PCM保存在old-unsafe-template-pcm/identity.json；
最终55 reader拒绝older format。中间54不是验收版本，旧53证据不
改写为55结果。unsafe-scope-evidence.json记录最终source/binary/
运行库/日志摘要；goal保持active，无需外部条件即可继续类region修复。

## 2026-10-14：AST60 类 region 结果与依赖 tuple

接续 AST55 的真实 box_test 阻塞，实现借用结果对类声明 region 的投影。
字段 region、显式 self 来源及 outlives 关系进入类型契约、实例化、PCM
和 Flow；接收者存储期不能替代所借对象。构造、字段写入、返回和函数
指针转换保留契约，unsafe 调用也不能绕过。class_region_results 在
local/PCM、O0/O2、普通及 ASan/UBSan 通过8次执行、120次拒绝。
同 region 来源合并仍保守，类值结果、嵌套投影及完整生命周期未实现。

原样 box_test 的完整依赖进一步暴露依赖 tuple 布局崩溃，已修复 tuple
类型依赖性、元素类型包替换、tracked tuple 表达式包和空包展开。
类型缓存改用 canonical 类型身份；生成类型名稳定编码类型，导入后
直接复用结构声明，解决 PCM 懒加载尚未注册类型时出现的双重名义身份。
这是内部 tuple 类型命名，不声称完整 Circle ABI。临时 tuple splat
物化尚未建模，明确拒绝。tuple_dependent 已加入完整 gate，8次执行
覆盖 local/PCM、O0/O2、ASan/UBSan，8次不支持临时量的拒绝检查。
中间 AST56–59 为开发版本，最终 AST60 reader 拒绝实际55及59 producer
的 older-format PCM。未改写历史验收绑定。

最终60 full gate退出1，仅 std2_consumers.py 失败；默认 Clang 差分
13/13，99个 pristine 文件无 fuzz 重放，固定上游树 clean。官方仍
1/14（ptr2 空 main），原样 box_test O0 编译链接119个错误、无可执行
文件；依赖 tuple 崩溃和类 getter 结果投影错误消失。输出专用 binder
仍被错误近似 static，类值结果、原始 slice 来源和 drop-only 仍是缺口。
class-tuple-evidence-v60.json 绑定源码、实际二进制、运行库、日志及引用。

随后最小 class-ctor-dependent-v60.cpp 发现新初始化检查的模板误报：
未实例化模板中的非依赖 View<unsigned> 构造体尚未实例化；实例化外层
模板后同代码通过。需先获得构造体再检查，不能删除真实未初始化反例。
局部检查与 sanitizer 不构成整个编译器无 UB 证明；goal 保持 active。

AST60 后续修复上述构造体误报：非依赖类特化即使出现在尚未实例化
函数模板里，也先实例化实际构造体，再检查借用字段初始化；unsafe
调用同样执行该检查。新模板 safe/unsafe 正例及未初始化反例通过，
class_region_results 达到8次执行、136次拒绝。原样 box_test 的六个
初始化误报消失，最终 O0 编译链接仍113个错误、无可执行文件。
重新构建后的完整 gate 仅 std2_consumers.py 失败；默认差分13/13、
99文件无fuzz重放、固定官方集合1/14，实际55/59旧PCM仍拒绝。
另 tuple_lifetimes 验证非平凡 tuple 元素在拥有参数返回、单字段
relocation 和异常退出时恰好析构两次，local/PCM O0/O2、普通及
ASan/UBSan 共8次执行通过。此专项另行运行，不谎称已包含于完整gate。
class-tuple-ctor-evidence-v60.json 绑定此最终二进制及实际源码、日志。
前一 class-tuple-evidence-v60.json 保留为修复构造时机之前的历史绑定。

## 2026-10-14：AST63 安全基础契约与表示写入

当前用户目标调整为把借用、拥有转移、析构和模块安全基础推进到完整，
暂缓跨模块实现；没有把既有局部通过重新定义成100%。本轮接续已有
AST61静态类值、AST62 unsafe返回来源工作，关闭实际已复现的漏检。

静态类值结果/参数与类型别名、函数指针保留carried regions；泛型类
use-site生命周期参数恢复解析，static结果即使有其它binder也保留证明。
unsafe函数返回来源现在检查局部对象和错误参数，未建模的非static
类值返回及无来源结果明确拒绝，不能把这种拒绝当作功能实现。
class-dynamic-escape-v61与unsafe-borrow-source-v61曾被实际旧编译器
接受；开启ASan detect_stack_use_after_return=1均检测到真实悬垂。
默认ASan的未报错不能充当这些程序安全的证明。

class-static-memcpy-v62进一步发现：unsafe memcpy把局部指针写入
View后，原有static借用证明仍被保留并从safe函数返回；真实运行产生
stack-use-after-return。AST63拒绝擦除原生借用句柄及含借用对象的
存储地址表示，覆盖void*/整数转换、memcpy/memset及数组；unsafe
权限不能替代被覆盖字段的生命周期证明。普通整数memcpy正例继续通过。
这是明确拒绝未建模字节互操作，不是完整堆/字节写入模型，也不声称
阻止unsafe中的所有UB。实际61/62 producer PCM被63 reader拒绝older
format；保存生产时源码/动态库/PCM摘要，不伪造旧版本标记。

最终full gate还揭示默认赋值误报：隐式/defaulted赋值返回receiver的
来源证明原先依赖操作被分类safe。现独立记录其borrow.this契约，即使
赋值本身unsafe；lambda仍按自身效果检查，不扩大权限。phantom_data
原测试在O0/local/PCM/ASan/UBSan恢复通过，未降低断言或改删失败用例。

最终frontend-v63-final.log退出1，保留三项失败：borrowed_containers、
mutable_borrows及原有std2_consumers。前两项因更严格的unsafe返回来源
检查暴露原始堆storage[index]来源未被建模，并非地址转换诊断。
heap-borrow-return-v63.cpp/log保留独立复现；不能靠恢复unsafe跳过
返回契约获取通过。需真正传播堆中元素与owner区域之间的关系，保留
搬迁、析构及越界约束；这是下一共享阻塞，无需外部条件即可继续。

最终gate包含静态类值8次运行/168次拒绝，unsafe返回8次运行/56次
契约权限拒绝及24次明确未建模签名拒绝。拥有参数、整体/字段/嵌套
relocation、替换、正常/EH cleanup、精确tuple析构和相关借用回归通过。
默认Clang有限差分13/13，99文件无fuzz重放，三个固定上游树clean。
最终原样box_test实际O0编译链接仍108个错误，无可执行文件；默认赋值
修复前中间版本为110，历史日志不混用。官方集合仍1/14，仅ptr2空main。

不用模板的examples/segment-tree/main.cpp在最终二进制O0/O2、普通
与ASan/UBSan四次运行通过，每次32000次随机区间操作对照；两个借用
冲突拒绝。此例拥有固定数组，不使用unsafe或返回借用；不能替代官方
安全库验收，也不能证明完整生命周期支持。

foundation-evidence-v63.json绑定最终源码、driver、libclang-cpp、
ASan/UBSan运行库、固定上游及日志。仍缺非static类值结果、生成式
生命周期、复杂嵌套投影、堆来源传播、部分drop-only和默认函数效果
语义等；暂缓跨模块不消除这些缺口。goal保持active，不标记100%。
测试和局部sanitizer验证不是整个编译器无UB证明。

### AST63 后续：函数地址、回调模板与依赖调用效果

接续堆容器失败沿现有模型检查：裸指针字段的storage[index]不能仅凭
borrow.this获得来源证明。拥有存储与元素carried regions需分别建模，
本轮没有按类名/sequence注解直接赋予this来源，也没有恢复unsafe跳过
返回契约；两个堆容器缺口仍保留。

另关闭一项实际用户规则偏差：DeclRefExpr原先把取得unsafe函数地址
当成unsafe调用。现在函数声明引用保留类型/实例化检查，实际CallExpr
才要求调用权限；safe函数可以保存unsafe函数地址，直接或间接调用
仍需显式unsafe块。旧run.py中仅取地址负例按用户调用规则改为正例，
并非删除失败用例或降低调用检查；unsafe_dynamic_callback等负例保留。

第一次移除地址误判后，完整gate发现syntax-only类型擦除回调误接受：
unsafe块内取safe模板trampoline地址时，实例化检查被Unchecked条件
跳过。现safe模板函数体独立检查，不继承取得地址处的unsafe权限；
新增原生类型擦除trampoline负例。不能把这个syntax-only漏检描述为
已证明有错误可执行文件或已接受旧PCM；独立Bridge的precompile尝试
事实上被拒绝，尝试日志保留，不伪造成功producer。

再次核对官方std2.h:1780发现依赖参数导致CallExpr提前跳过已知unsafe
callee；之前DeclRefExpr的误判掩盖此缺口。现对已解析且非依赖的callee
立即检查效果，参数/生命周期仍在替换时检查。最小dependent-unsafe-
call-v63.cpp原先syntax-only接受，新专项覆盖拒绝及显式unsafe泛型
包装的实际运行。中间box107错误不是兼容进展，最终恢复应有诊断，
原样box O0编译链接仍108错误、无可执行文件。

最终native_function_addresses在O0/O2、普通/ASan/UBSan共4次执行、
32次拒绝通过，新增于完整gate；run.py的368编译及模块运行用例通过。
最终frontend-address-dependent-v63.log退出1，只保留borrowed_containers、
mutable_borrows、std2_consumers三项失败，其余支持范围回归通过。
默认Clang13/13，官方仍1/14(ptr2空main)，三个固定上游树clean；补丁
未改变，99文件无fuzz证据按相同patch摘要复用。AST布局与类型元数据
未修改，保留63；构建更新checker fingerprint。function-address-evidence-
v63.json绑定最终源码/动态库/运行库和日志；此前各构建记录保留历史绑定。
非static类值结果、生成式生命周期、堆来源、drop-only及默认效果等仍
未完成，不标记安全基础100%，goal保持active，继续实际共享阻塞。

## 2026-10-14：AST65 借用元素 owner 契约的写入入口

用户目标按顺序细化为：先补齐借用/生命周期的类值返回、嵌套投影、
generative及复杂来源，再推进拥有转移、析构、模块调用组合；暂缓跨
模块新实现。四项均不能认定完整，旧粗估百分比不作为验收。

沿两个失败堆容器的写入路径找到前置漏检：unsafe函数可把foreign
owner的View传给带safecpp.unsafe.adopts.borrow声明契约的safe push。
unsafe-adoption-v63.cpp曾由实际63编译器接受，真实63 producer PCM
及其源码/动态库摘要已保存。AST64使unsafe函数中涉及stores/adopts
的调用进入契约分析；来源未知或不属于receiver的owner区域时用
unconditional contractError拒绝，不恢复unsafe跳过借用检查。

随后unsafe-adoption-member-v64.cpp发现成员指针丢失adoption契约，
实际64 precompile也接受，真实producer另行保存。最终65明确拒绝
这类未建模的间接契约暴露，即使位于unsafe；没有声称成员指针已完整
支持owner契约。adoptedParameters按声明时的参数索引归一化，继承
注解不按定义的新名字重新绑定；验证契约须为非static方法，且参数名
存在、参数类型能够携带借用。拼错名称、static方法及纯值标量声明
不再静默忽略。实际63/64 PCM由65 reader拒绝older format。

adoption_contracts在O0/O2、普通及ASan/UBSan共4次运行通过：safe、
显式unsafe块、unsafe函数均执行owner约束，重声明参数改名正例通过；
20次owner来源拒绝、12次无效声明拒绝，另8次间接暴露的未建模拒绝。
后者不计作完整功能或官方安全负例通过。本轮检查沿既有声明契约实现，
不是以自定义容器替代官方Safe C++验收，也不证明unsafe中所有内存
操作安全，更没有建立完整堆存储/元素来源模型。

最终frontend-adoption-v65.log退出1，仍三项失败：borrowed_containers、
mutable_borrows、std2_consumers；其它支持范围回归通过。默认Clang
有限差分13/13，99文件无fuzz重放，三个固定上游树clean。官方仍
1/14，仅ptr2空main，未新增安全库端到端通过。旧63/64日志绑定原有
构建，adoption-evidence-v65.json绑定最终65源码、二进制、运行库及日志。

第一项下一复现为class-value-return-valid-v65.cpp：View/a wrap/(a)
(const unsigned^/a input)返回View{input}，应保留参数借用来源，但实际
O0编译链接仍因非static类值结果未建模和缺失结果来源元数据等5项
诊断失败，无可执行文件。不是安全负例成功。需把类值carried region
映射进函数类型及返回/调用投影，处理多region、嵌套及generative语义，
不能只删掉当前拒绝检查。后续按用户四项顺序推进；goal保持active。

## 2026-10-14：AST67，优先输出专用（generative）生命周期

用户将 generative 生命周期调整为第一优先级。AST66 已接通单区域、
直接标量借用字段的非static类值结果：参数carried region进入函数类型，
返回与调用投影保留来源；直接/函数指针/模板调用、按值转发、独占借用
拥有转移覆盖于class_value_results。最终67重复验证4次O0/O2普通及
ASan/UBSan运行、48次拒绝；不代表多区域、嵌套和完整类值返回已完成。

五个实际66最小复现保存在generative-v66目录及其二进制绑定记录：
原始借用的输出专用binder被编码为static来源，而简单类值的同类签名
被直接拒绝。67增加独立ReturnBorrow编码，保留量化结果绑定，不再
把输出专用函数类型编码为显式/static。源索引解码、声明契约验证、
unsafe函数体契约分析和函数指针转换同步处理；不允许擦除或伪造该
契约。类值结果的where a:static也归一化为显式static种类。

支持永久非TLS来源的原始借用及简单类值输出专用返回、模板实例化、
直接和间接调用。类型标记独立并不等于构造了任意裸指针的新生命周期：
函数体仍要求真实永久来源；局部或独立输入区域的逃逸无条件拒绝，
未知裸指针来源明确报未建模。调用端暂以永久摘要处理这个已验证路径，
不能声称已有逐调用新区域、裸指针来源、分配/释放或完整generative模型。

generative_lifetimes加入完整gate：本地/新PCM、O0/O2、普通及
ASan/UBSan共8次实际运行，88次契约/权限拒绝，16次裸指针来源未建模
拒绝。最后一项不是安全反例成功。真实66 producer PCM在67链接前
保存，67 reader拒绝older format；未伪造旧版本PCM。第一版专项把
长期全局借用与效果未知的函数指针调用组合，触发现有全局失效检查；
改为逐次读取并核对全部六个结果。显式safe lambda拼写尚未支持的
语法失败日志保留，权限反例使用当前支持的lambda拼写，要求unsafe
调用诊断而非语法错误。unsafe_result_contracts中原有View/a局部逃逸
反例保留，改为验证实际generative逃逸原因，不再按签名未实现计数。

最终frontend-generative-v67.log退出1，仍仅borrowed_containers、
mutable_borrows、std2_consumers三项失败。默认Clang13/13，99文件
无fuzz重放，三个固定上游树clean。官方仍1/14 syntax-accepted，
仅ptr2空main；原样box_test实际O0编译链接仍108错误，无可执行文件。
std2.h:68的slice_from_raw_parts现明确报generative裸指针来源未建模，
没有取得官方安全库新增端到端通过。generative-evidence-v67.json
绑定最终源码、driver、动态库、ASan/UBSan运行库、上游和完整日志。

下一实际阻塞是裸指针与slice构造的来源传播：区分外部输入、已知局部
owner和未知来源，处理指针拷贝/改写/逃逸、调用侧生命周期和slice
extent约束。不能把未知来源统一变成static或删除返回检查来通过。
多区域/嵌套投影、拥有转移复杂组合、drop-only及模块/ABI组合仍未完成；
goal保持active。专项和sanitizer运行不是整个编译器无UB证明。

## 2026-10-14：AST68/69 生成式裸指针来源（补记）

上一轮把 AST67 之后的实际实现补齐记录。AST68 为生成式裸指针建立
**来源（owner）跟踪**：区分外部输入指针、已知局部 owner 与未知来源，
并处理指针的复制、赋值与条件合并。每个外部指针参数对应一个抽象
区域根，`p=q`、`q=p`、三元合并只在所有分支来源已知时保留；alias
经未知函数调用、`delete`、取地址逃逸后进入失效集合，后续借用构造
因未知来源明确拒绝。生成式函数的**调用端**由实参指针的来源重连到
调用者的实际 owner，因此 `raw(q)`、经函数指针 `fn(q)`、包装函数及
类值结果在同一规则下取得来源，而不是把未知指针统一变成 static。

AST69 完成同一模型的**跨单元与 legacy ABI 复验**：`tests/
generative_pointer_origins.py` 在本地与 producer PCM、O0/O2、普通及
ASan/UBSan 下共 8 次实际运行，168 次拒绝，覆盖外部指针 owner、
复制/赋值/合并、直接与间接调用、类值结果、safe 包装函数，以及
legacy C provider 的标量借用 ABI。分类证据见
build/implementation-baseline/generative-pointer-v69.log（本轮 8 次运行）。
旧 producer PCM 保存在 generative-pointer-producer-v67 与
static-borrow-variable-producer-v68 下，实际由各自旧二进制生成，v69
reader 明确报 older format（pointer_api-reader.log、static_var-reader.log）。

同一轮重新检查了官方 std2.h 的 raw slice 构造：
generative-pointer-v69/original-slice-construction.cpp 保留
`^*__slice_pointer(p, n)` 的最小复现，当前仍报 "generative raw borrow
construction provenance is not yet modeled"。AST 形式为
`UnaryOperator '^'` 包住隐式 `__slice_pointer` 内建调用（其子节点为
指针实参与长度实参），即 slice 值构造而不是普通函数调用；`^const *p`
的既有路径不覆盖它。未把未知来源当作 static 放行，也未删除该拒绝。
generative-pointer-v69/unused-pointer-permanent.cpp 另行确认：取到
尚未使用的生成式/永久函数地址也不能把局部地址洗成 static 来源。

最终 AST69 完整 frontend gate 为 frontend-generative-pointer-v69.log，
退出 1，失败脚本为 borrowed_containers.py、mutable_borrows.py、
std2_consumers.py；默认 Clang 有限差分 13/13，官方集合 1/14（ptr2
空 main），99 文件补丁无 fuzz 重放，三个固定上游树 clean。该轮没有
更新本文档，故在此补记；其证据文件为
default-generative-pointer-v69.json、circle-generative-pointer-v69.json
与 patch-generative-pointer-v69.log。

## 2026-10-14：AST70 借用序列的元素存储区域

接续 AST68/69 的生成式来源工作，先关闭上一轮完整 gate 里的两个实际
失败（borrowed_containers、mutable_borrows），它们都是同一个前置缺口：
**经过审计的容器把元素放在自己的堆存储里，元素读出的借用来源没有
模型**。两处失败点是 runtime/borrows.cppm:101 的
`clone(values_[index])` 与 runtime/mutable_borrows.cppm:91 的
`return values_[index];`，此前都报 "returned borrow has unknown
lifetime provenance"：`values_` 是裸指针字段，其下标访问的根来源为空。

实现的是一个**声明的库契约**，不是按类名或按 sequence 注解直接赋予
this 来源：

* 元素存储字段用 `safecpp.unsafe.sequence.storage` 声明（与其它
  `safecpp.unsafe.*` 同族，属于库作者的审计责任）。读取该字段得到的
  元素 lvalue（`storage[i]`、`*(storage + i)`）的来源是**序列声明的
  区域**：对 receiver 即 receiver 自身，因此带 `borrow.this` 结果契约
  的取值函数成立；对同一类型的其它已知对象则取该对象的区域根。任意
  指针（`p->storage_` 且 p 不是 this）不产生来源。
* 该声明必须站得住：编译器拒绝非审计序列（缺
  `safecpp.unsafe.borrowed.sequence` / `safecpp.unsafe.exclusive.sequence`）
  的存储字段、元素类型不携带借用的存储字段，以及没有声明
  `stores.borrow:` / `stores.self` 存储区域的序列。元素类型为依赖类型
  时该条在实例化处判定；运行时容器是模板，故专项同时覆盖"依赖类型
  声明 + 实际实例化"这一形态，而不是只测非模板类。
* 结果契约仍逐条验证：没有结果契约的取值函数继续被拒；把元素的来源
  声明成其它参数区域时，函数体来源检查拒绝。契约只解释“元素借自本
  序列的区域”，不代替写入端的 `adopts`/owner 检查——push_back 仍要求
  被采纳元素的全部来源都在 receiver 区域内。

改动位置：`src/SafetyContracts.h` 新增 `sequenceStorageField` /
`auditedSequence`；`src/FlowAnalysis.cpp` 新增 `sequenceStorageBase` /
`sequenceElementRoots`，并在 `expressionRoots`、`referenceRoots`、
`rawPointerRoots` 三处接入；`src/ModuleSafety.cpp` 的类检查新增上述
拒绝；`runtime/borrows.cppm`、`runtime/mutable_borrows.cppm` 的
`values_` 字段声明该契约。没有改动 AST/PCM 编码，也未改写任何断言。

证据（source/binary/runtime 摘要见 sequence-storage-evidence-v70.json）：

| 检查 | 结果 |
| --- | --- |
| tests/borrowed_containers.py | 通过：堆区域增长、读取、移动、析构（ASan/UBSan）及 6 个拒绝 |
| tests/mutable_borrows.py | 通过：工厂来源、增长、句柄转移及 8 个拒绝（ASan/UBSan） |
| tests/sequence_storage_regions.py（新） | 通过：本地与 producer PCM 接受区域化元素读取；7 个契约拒绝 |
| CTest | 24/24（重建 AST 插件后，build/ctest-sequence-v70.log） |
| 完整 frontend gate | frontend-sequence-v70.log 退出 1，唯一失败 std2_consumers.py（此前为 borrowed_containers、mutable_borrows、std2_consumers） |
| 默认 Clang 有限差分 | 13/13（default-sequence-v70.log） |
| 官方集合 | 1/14 语法接受（ptr2 空 main），Circle 库示例 0/6（circle-sequence-v70.log）；未新增端到端通过 |
| 补丁重放 | 补丁未改动（SHA256 492b26b1…），pristine 22.1.2 无 fuzz 重放 99 文件匹配 |
| 原样 box_test | O0 仍 115 错误、无可执行文件；首个阻塞 std2.h:68 现在报出真实原因：raw slice extent is not proven within a known allocation |

box_test 错误数由 AST67 记录的 108 上升到 115，来自 AST68/69 更精确的
裸指针来源拒绝（例如 "generative raw call requires known live pointer
provenance"），不是本轮新增。本轮新增的存储契约对官方头文件不生效，
新日志中没有一条 "element storage" 诊断。

借生成式裸指针这条线，本轮同时把官方 std2.h:68 的真实缺口定住了。AST
比对显示 `^*__slice_pointer(p, n)` 并不是内建调用，而是
`UnaryOperator '^'` 包住一个 **slice 初始化列表**（元素为指针与长度），
现有规则已经覆盖"指针是可证明的常量数组 + 长度是分配内的常量"这一
形态（tests/static_fields.py 的 `mutable_text` 正例保持通过）。因此缺的
不是指针来源，而是**动态长度**这一前置条件：长度可以是任意运行时值，
检查器无法把它约束在来源分配内。本轮把该情形单独报出
("raw slice extent is not proven within a known allocation")，而不是笼统
说来源未建模；没有为通过官方头文件而放行动态长度。tests/
generative_lifetimes.py 增加该拒绝用例（16 个 raw-provenance 缺口）。

剩余阻塞按用户给定顺序：借用/生命周期的**动态 slice extent 约束**仍是
第一项（需要真正的长度-分配关系模型，或按固定 draft 把未标记函数归为
unsafe 并由调用方承担前置条件——后者会动到当前"未标记定义默认 safe"的
既定差异，需独立决定）；随后是 std2_consumers 暴露的官方头文件 mut
receiver 隐式可变借用与老式双重解引用。拥有转移的复杂泛型/legacy ABI
组合、drop-only 与组合析构、模块/ABI 组合验证仍未完成。四项均不标记
100%，goal 保持 active；局部测试与 sanitizer 不是整个编译器无 UB 的
证明。

## 2026-10-14：AST71 slice 重建的区域与长度传播

接续 AST70 定住的官方 std2.h:68 缺口。上一轮确认该处不是内建调用而是
`UnaryOperator '^'` 包住 slice 初始化列表（元素为指针与长度），并确认
"常量数组 + 分配内常量长度"已由既有规则覆盖、缺的是**动态长度**这一
前置条件。本轮先把其中**可证明**的那部分做掉：同一个 slice 的数据指针
与长度的重建。

规则：`^*__slice_pointer((*s)~as_pointer, (*s)~length)` 中，指针来自
`~as_pointer`、长度来自 `~length`，两者指向**同一个 slice 位置**，且
结果元素与源元素大小相同（复制的长度按源元素计数，字节范围才一致），
则重建出的 slice 借用**该位置的区域**、覆盖**完全相同的字节**。任一半
来自别处、长度不是该 slice 自己的长度、或从裸指针重建，全部继续拒绝；
裸指针形态（官方 `slice_from_raw_parts` 的定义体）保持
"raw slice extent is not proven within a known allocation"。

实现位于 `src/FlowAnalysis.cpp`：新增 `sliceProjectionPlace`（识别
`~as_pointer` / `~length` 投影背后的 slice 位置，`*borrow` 与 borrow
本身归到同一位置）与 `sameSliceElementSize`（元素大小一致），并在既有
slice 初始化列表规则里增加该分支返回该位置的 roots。没有新增信任：区
域身份沿用源 slice 的区域，因此既有的排他性、NLL 与生命周期规则照常
生效——实测"unsafe 中建立可写重建、之后在 safe 代码里读源 slice"报
`access conflicts with a live exclusive borrow`，而未再被使用过的重建
按 NLL 正常失效。

`tests/slice_rebuild_regions.py`（新，已进完整 gate）在模块 + producer
PCM、O0/O2、普通与 ASan/UBSan 下实际运行：同一 slice 的重建、二级重建、
`unsigned char`→`char` 的同尺寸重解释、以及可写重建后写回并读回；另有
5 个拒绝（运行期长度、常量长度、官方裸指针形态、活跃排他重建与源冲突、
把共享 slice 交给可变 slice 形参）。slice_rebuild-evidence-v71.json
绑定源码、driver、libclang-cpp、插件、ASan/UBSan 运行库与上述日志。

最终 frontend-slice-v71.log 退出 1，唯一失败仍为 std2_consumers.py；
CTest 24/24，默认 Clang 有限差分 13/13，官方集合 1/14（ptr2 空 main）、
库示例 0/6，补丁未改动故 99 文件无 fuzz 重放结论沿用。原样 box_test O0
仍 115 错误、无可执行文件，首个阻塞仍是 std2.h:68。

剩余阻塞（按用户顺序）：借用/生命周期线——生成式 slice 的**调用侧动态
长度**仍需模型（本轮只接受"同一 slice 自己的长度"，不接受任意运行期
长度或子区间），以及多区域/嵌套类值投影；随后是 std2_consumers 暴露的
官方头文件 mut receiver 隐式可变借用与老式双重解引用。拥有转移的复杂
泛型/legacy ABI 组合、drop-only 与组合析构、模块/ABI 组合验证仍未完成。
四项均不标记 100%，goal 保持 active；局部测试与 sanitizer 不是整个
编译器无 UB 的证明。

## 2026-10-14：AST71 附：前端补丁再生工具与下一项前置

本轮同时补齐长期缺失的工具链步骤。前端补丁 `frontend/clang-22.1.2.patch`
与 `frontend/source-hashes.json` 此前只能靠一次性的手工 diff 维护，
任何 Sema/Parse/AST/CodeGen 改动都缺少可复现的再生成与自证入口。新增
`tools/regenerate_frontend_patch.py`：从固定的 pristine 源码包提取文件、
对工作树做 `diff -u`、写回累计补丁与逐文件摘要；`--check` 在临时目录
再生，并把结果实际应用到全新 pristine 提取上，逐文件与工作树比对。
当前源码下 `--check` 通过：**再生补丁无 fuzz 应用并逐文件重现工作树
99 个文件**（补丁字节与提交文件不同，内容等价；提交的补丁摘要与工作树
逐文件摘要仍然一致：99 文件零漂移）。该工具使后续前端改动的证据链可
重建，已加入 VERIFICATION.md 的复现命令。

下一项（按用户顺序，借用与生命周期）为**多区域类值返回**。本轮已用
最小复现定位：语法是类型侧的重复斜杠 `Pair/a/b`（`struct Pair/(a,b)`
定义类、`Pair/a/b` 作为类型实参序列，解析器按 `while (Tok.is(slash))`
收集参数），当前在
`ModuleSafety.cpp` 报 "non-static class-value result lifetimes are not yet
modeled"（`circleSimpleClassValueRegion` 只接受单区域、直接标量借用
字段），随后在函数类型推断处报 "native borrow result requires a checked
lifetime contract"：`CircleClassLifetime.h` 的 bound-signature 解析只解出
单个 `ClassResult` 名字（patch 侧）。因此该项需要两侧改动：
patch 侧为多区域类值结果解析每个字段的区域 binder 并写回
`ReturnBorrowSources` 与结果绑定编码（可能触及 PCM 类型编码与 AST 版本），
检查器侧在返回检查里按字段区域逐条比对来源、并在调用点按字段投影
区域。嵌套（字段本身是另一个带区域类值）还需要前端的字段投影标记
（当前只为声明符上的 `/a` 与生命周期 binder 模板参数添加
`safecpp.native.lifetime_projection`）。这些尚未实施，不能算已支持。

四项进度仍不标记 100%，goal 保持 active。

## 2026-10-14：AST72 多区域类值返回（借用与生命周期线）

本轮把"类值返回"从一个区域推进到**每个字段一个区域**。类型侧的
`Pair/a/b` 已能作为结果类型：`Pair/a/b build/(a,b)(const unsigned^/a x,
const unsigned^/b y)` 声明两个区域，返回值的每个字段按**该字段自己的
区域**逐条比对——把两个字段对调、把同一 owner 同时给两个区域、或让某
个字段去借另一个区域绑定的参数，都会报
`class-value result field does not borrow from the parameter bound to its
region`；值活着时改任一 owner 报 `mutation conflicts with a live borrow`；
把局部值的字段返回出去报 `returned borrow has unknown lifetime
provenance`。

实现分两侧。patch 侧 `CircleClassLifetime.h` 新增
`circleMultiRegionClassValue`（绑定要覆盖记录声明的全部区域，且字段都是
直接标量借用并各自带区域），`SemaType.cpp` 的 binder 分支把结果类型命名
的每个区域都解析成节点、算出可达来源并写回函数类型的来源表（PCM 里因此
保留了契约）。检查器侧 `SafetyContracts.h` 把多区域类值与"字段→区域名"
暴露给检查器，`ModuleSafety.cpp` 不再把这类结果判为未建模，
`FlowAnalysis.cpp` 新增 `classResultFields` 在返回处逐字段验证，并在
`projectedPayload` 里把导入结果的每个字段接到"参数标签等于该字段区域"
的实参上。顺带修掉上一轮遗留的构建破坏：`classResultFields` 在
`#ifdef MODULE_SAFETY_BUILTIN` 内，而调用点在 ifdef 之外，standalone
插件（不带 builtin）编译失败；调用已加同样的条件编译，`cmake --build
build` 恢复。

**来源传播（复杂来源）**：别名不洗白区域，检查器跟的是借用的**来源**
而不是写法。`const unsigned^ first = x; return Pair{first, y};` 在
`Pair/a/b` 结果里被接受，而 `const unsigned^ alias = y; return
Pair{alias, y};` 被拒绝——这正是"复杂来源传播"要的性质，已作为正向用例
写进测试。上一轮遗留测试里那条 `const unsigned^/a alias = x;` 的期望
本身是错的（声明符上的 `/a` binder 在局部变量位置本就拒绝，且语义上
`Pair{alias, y}` 应被接受），已替换成上面两个真正有判别力的用例。

`tests/multi_region_class_values.py`（新，已进完整 gate）在本地定义与
producer PCM 两条路径、O0/O2、普通与 ASan/UBSan 下实际编译运行，并额外
验证：模块安全-only 的消费者（`-fmodule-safe`，无 `-fcircle-borrow-values`）
直接读 PCM 上的契约也能拒绝活跃借用的写入；借用模型消费者链接模块对象
运行通过。共 7 个拒绝。证据
`build/implementation-baseline/multi-region-class-value-evidence-v72.json`
绑定源码、driver、libclang-cpp、插件与各日志；补丁 `--check` 无 fuzz 重放
并逐文件重现工作树 99 文件。

**仍未完成（本条不标 100%）**：嵌套投影——字段本身是另一个带区域的类值
（`struct Outer/(a) { Inner/a inner; };`）仍拒绝，报
`borrow value fields require class lifetime parameters` 与
`non-static class-value result lifetimes are not yet modeled`；前端只为
声明符 `/a` 与生命周期 binder 模板参数写
`safecpp.native.lifetime_projection`，不会为"类值类型字段"写，且
`circleSimpleClassValueRegion`/`circleMultiRegionClassValue` 明确要求
字段是直接标量借用。这是本线下一项。生成式生命周期线上，
`generative_lifetimes.py`/`generative_pointer_origins.py` 的裸来源
（`delete p` 后返回别名、间接 `touch(p)` 效果未知等）仍保守拒绝，
需要间接调用效果模型，不是本轮范围。四项进度仍不标记 100%，goal 保持
active；局部测试与 sanitizer 不是整个编译器无 UB 的证明。

## 2026-10-14：AST73 嵌套类值投影（借用与生命周期线）

本轮补上"嵌套投影"。`struct Outer/(a) { Inner/a inner; }` 现在可声明：
字段类型把**内层记录的 region 绑定到外层记录自己的 region**，因此通过
嵌套值读到的借用跟随该 region 的 owner。已验证的形态：两层与三层嵌套、
一个外层记录里的多个嵌套字段（`Pair2/(a,b) { Inner/a first; Inner/b
second; }`）、以及**改了名字的映射**（`struct Mapped/(a,b) { Inner/b
first; Inner/a second; }` —— 字段名不用等于 region 名，解析走外层记录）。
复制（隐式 copy ctor）、relocation 与按值传参都保留投影；把两个嵌套字段
对调、映射字段从另一个 region 取源、从局部量取源、同一 owner 供两个字段，
分别报 `class-value result field does not borrow from the parameter bound
to its region` / `returned reference does not borrow from the declared
lifetime source`；值活着时改任一 owner 报 `mutation conflicts with a live
borrow`。

实现：前端（`SemaDecl.cpp`）为"类值类型字段"补 `safecpp.native.
lifetime_projection` 与字段所属外层 region 的注解，并让其 region 名在外层
记录里解析；`CircleClassLifetime.h` 用新的 `circleRegionFieldShape` 取代
原来"字段必须是直接标量借用"的循环——字段可以是同形状的嵌套类值，深度
上限三层；检查器侧 `regionLabels` 沿投影路径逐层解出叶子的 region 标签
（嵌套字段的类型写的是**外层**作用域的名字，要经上一层解析），
`classRegionRoots` 的选择器同时接受"嵌套值自身的 loan"（其 roots 就是
region roots），`classFieldValue` 对嵌套字段从嵌套构造实参取 region 来源。
本轮还修掉了 `classResultFields` 里 `Leaf.append(临时.begin(),
另一个临时.end())` 的 UB（两个不同的临时 vector 端点导致 SmallVector
巨型增长崩溃）。

未建模的嵌套形状在**字段声明处**保守拒绝，而不是静默接受：两个 region 的
嵌套字段、`static` 嵌套字段、以及名字在外层记录里不存在的嵌套字段都报
`borrow value fields require class lifetime parameters`（该消息读起来重复，
属于既有 reject 约定）；第四层及更深的嵌套被 `circleRegionFieldShape`
拒绝。`tests/nested_class_values.py`（新，已进完整 gate）在本地与
producer PCM、O0/O2、普通与 ASan/UBSan 下实跑，含 11 个拒绝；证据
`build/implementation-baseline/nested-class-value-evidence-v73.json`。
门禁：CTest 24/24，默认 Clang 有限差分 13/13，官方集合 1/14（0/6 库示例），
完整前端 gate 仍只失败 `std2_consumers.py`；补丁 `--check` 无 fuzz 重放并
逐文件重现 99 文件；原样 box_test O0 仍 115 错误、无可执行文件。

本轮不把借用/生命周期线标为 100%：生成式生命周期的裸来源（`delete p`
后返回别名、效果未知的间接 `touch(p)`）仍需间接调用效果模型；`std2.h`
官方头文件的 `mut receiver` 隐式可变借用与老式双重解引用仍待实施；
拥有转移的复杂泛型/legacy ABI、drop-only 与组合析构、模块/ABI 组合验证
仍未完成。goal 保持 active。

## 2026-10-14：AST73 附：std2_consumers 阻塞的精确定位

唯一仍红的 `std2_consumers.py` 本轮缩小到最小复现：接收者为 `self^`
（可变接收者）的方法在**隐式**调用形式下无法通过重载解析——

```cpp
template<class T> struct S { T value; void set(self^, T v) safe { self->value = v; } };
int main() safe { S<unsigned> s{1}; s.set(2u); }
// error: no viable conversion from 'S<unsigned int>' to 'S<unsigned int> ^'
```

写 `(mut s.set(2u))` 可以，说明缺的是**调用点隐式形成可变接收者借用**
（`obj.mut_method(...)` 自动插入 `mut obj`），而不是接收者语法本身。
`tests/mutable_context.py` 里 `cell.choose()` 之所以通过，是因为类里同时
有 `choose(const self^)`，隐式调用绑到共享重载、只有显式 `mut` 才选可变
重载——所以这项改动必须保持"有共享重载时隐式调用仍选共享"的既有语义，
属于会动重载解析的改动，本轮不做。std2.h 的 `s.append(...)`、
`v.push_back(...)` 正是只有可变重载的形态；`*v[1]`/`*(*b)` 的
"indirection requires pointer operand ('int' invalid)" 同源于该处解析
失败后落到按值返回。

## 2026-10-14：AST74 裸指针 slice 的 extent 作为"未验证代码的声明"（generative 生命周期线）

生成式线上还剩三类"未建模"的裸来源，本轮消除其中与 slice 有关的一半：
`^*__slice_pointer(p, n)` 这类"裸指针 + 长度"构造此前在**任何**上下文都被
拒绝（`raw slice extent is not proven within a known allocation`）。现在它
与标量形态 `const unsigned^/a raw/(a)(const unsigned* p) unsafe { return
^const *p; }` 遵循同一条规则：**当函数体自身的声明不由检查器验证时
（`unsafe` 函数／未经检查的函数体），extent 是这段代码的声明**，而结果的
**区域**仍然在每个调用点重连到实参自己的来源。于是
`const [unsigned char;dyn]^/a slice_of_parts/(a)(const unsigned char* p,
unsigned long n) unsafe { return ^*__slice_pointer(p, n); }` 可以声明，
调用方在 unsafe 区域里 `slice_of_parts(buffer, 4u)` 拿到指向自己数组的
slice，并可读长度与元素（本地与 PCM 导入两条路径、O0/O2、普通与
ASan/UBSan 实跑）。

实现只在 `src/FlowAnalysis.cpp`（检查器侧，属于 `build_frontend.py` 拷贝的
四个文件，不在 99 文件补丁内，故补丁字节未变）：把 `unprovenSliceExtent`
里的"取回返回表达式形成的 slice 构造"提成 `rawSliceConstruction`；generative
返回检查新增 `ClaimedExtent`——仅当 `ContractsOnly`（检查器不验证该函数体
的声明）且指针操作数的来源全是**永久存储或外部指针根**时才接受。来源这一条
是关键：没有它，`char local[8]; return ^*__slice_pointer(local, n);` 会借
我新增的分支逃逸出局部量（本次实现过程中确实先出现了这个洞，已用
`permanentRoot || ExternalPointerRoots` 补上，并有反例覆盖）。

**保守面保持不变**：检查器验证的函数体（含 keyword-less 函数体）里，
extent 必须自己可放置，因此"从形参取 extent"仍拒绝（
`raw slice extent is not proven within a known allocation`）；把局部量的
存储交给该构造并返回结果仍拒绝
（`generative return lifetime cannot expose a local or input-bound owner`）。
`tests/slice_rebuild_regions.py` 把"裸指针 + 计数"从拒绝清单移入可编译 API
并实跑，新增三条反例（checked body 从形参取 extent、局部数组作源、以及
局部量经该构造逃逸），现在共 7 条拒绝；`generative_lifetimes.py`（88 条
契约拒绝）与 `generative_pointer_origins.py`（168 条拒绝）不变且通过。
证据 `build/implementation-baseline/raw-slice-extent-evidence-v74.json`
（含 `src/` 五个文件的 SHA256，因为检查器不在补丁清单内）。门禁：CTest
24/24，完整前端 gate 仍只失败 `std2_consumers.py`，默认 Clang 有限差分
13/13，官方集合 1/14（0/6 库示例）。

**仍未完成**：官方 `slice_from_raw_parts/(a)(const T* p, std::size_t n) ->
const [T; dyn]^/a` 没有安全关键字，本实现把 keyword-less 函数体当作**受检
函数体**，所以它的 extent 仍被拒绝，box_test 首个阻塞仍是 std2.h:68。
要把这条打通需要**延迟义务**：被调用方记录"哪个形参给指针、哪个给长度"，
每个受检调用点必须证明该实参对构成可放置的 extent（不能退化成"任意一对
实参可放置"，那是不安全的近似）。该形参映射本轮未实现。另需确认语义前
提：`#feature on safety` 下 keyword-less 函数究竟应视为 safe 还是 unsafe
（本实现目前按"受检"处理，测试套件也依赖这一点），这属于语言语义决定，
不由本轮单方面更改。

## 2026-10-14：AST75 受检调用点的 extent 义务（generative 生命周期线，官方形态打通）

AST74 之后"受检函数体不能声明来自形参的 extent"仍挡着官方形态。本轮把
义务**延迟到调用点**：

* 被调用方：受检函数体不再被无条件拒绝——当它的**单个 return** 就是
  `^*__slice_pointer(形参, 形参)`（指针形参 + 整数长度形参，两个不同形参），
  且指针来源是外部指针根时，接受该声明，把"extent 由调用者放置"作为义务。
  未受检函数体仍自行声明（AST74 规则不变）。
* 调用点：受检调用必须**放置**这对实参。可放置的两种形态：①同一 slice 位置
  的 `~as_pointer` 与 `~length`（沿用 AST71 的位置识别，字节范围完全一致）；
  ②已知常量大小数组的计数后缀（元素大小一致且常量计数不超界）。间接调用或
  返回形态不可读的调用在受检代码里仍拒绝。
* `generativeCallRoots` 增加一条：实参是某个 slice 自己的 `~as_pointer` 时，
  结果的区域接到该 slice 位置的区域（此前这里取不到 roots，导致
  `slice_from_raw_parts(s~as_pointer, s~length)` 这种"经调用重建"报
  `object borrow provenance cannot be established`）。字段名用生成的
  `__circle_data`/`__circle_len`（源码写法仍是 `~as_pointer`/`~length`）。

**实测**：官方 `template<class T> auto slice_from_raw_parts/(a)(const T* p,
std::size_t n) -> const [T; dyn]^/a { return ^*__slice_pointer(p, n); }`
现在可以声明；受检调用 `slice_from_raw_parts(local, 2u)`（局部数组后缀）与
`slice_from_raw_parts((*s)~as_pointer, (*s)~length)`（同一 slice 重建）都
编译并实跑读出正确元素；而"指针与计数指不出已知分配"、"计数超过数组"、
"间接调用"以及既有的局部量来源仍在受检代码里拒绝。
**原样 box_test O0 首个阻塞首次前移**：错误 115 → 108，第一处从
std2.h:68（`raw slice extent is not proven within a known allocation`）
变为 std2.h:396（`static return lifetime contract requires permanent
non-thread-local borrow origins`，即官方头文件自身的 static 契约），日志
`build/implementation-baseline/box-o0-slicev3.log`。

测试更新：`slice_rebuild_regions.py` 让"延迟构造"进入 API（受检调用两支），
反例 9 条；`generative_lifetimes.py` 把裸 slice 构造移入 API（受检调用放
置 extent），`unmodeled` 从 3 条降到 2 条、新增 3 条调用点反例，打印数值
改为按列表计算。门禁：CTest 24/24，完整前端 gate 仍只失败
`std2_consumers.py`，默认 Clang 有限差分 13/13，官方集合 1/14（0/6 库示例）。

**仍未完成**：extent 只能来自"同一 slice 自身的长度"或"常量数组的常量
后缀"；独立子区间长度、运行期长度、以及"指针来自对象字段、长度来自同一
对象尺寸"（官方 `slice(self.data(), self.size())` 形态）都仍拒绝——后者
需要把对象尺寸与指针的数据流关联起来。间接调用在受检代码里保守拒绝。
证据 `build/implementation-baseline/deferred-slice-extent-evidence-v75.json`。

## 2026-10-14：AST76 裸指针来源的两条剩余形态（generative 生命周期线）

本轮清掉 `generative_lifetimes.py` 里"未建模"清单的前两条，并补上调用点
extent 的**常量偏移后缀**：

* **经 void 的转换保留来源**：`rawPointerRoots` 的 `CK_BitCast` 分支此前要求
  两侧 pointee 类型相同，于是 `static_cast<const unsigned*>(void*)` 丢失来源。
  现在只要**任一侧 pointee 是 void** 就放行（referent 与来源都不变，与
  `const unsigned* p` 走同一条规则）。原拒绝用例
  `raw/(a)(void* p) unsafe {return ^const *static_cast<const unsigned*>(p);}`
  现在可编译并在 API/主程序里实跑。
* **已知数组内的常量偏移**：`rawPointerRoots` 接受 `array + k`——数组是编译期
  常量大小且 `k` 严格在数组内时，偏移指针指向该数组的区域；超出（含
  one-past-the-end）仍拒绝。于是 `raw(buf + 2u)`（`buf[4]`）可编译，
  `raw(buf + 5u)` 仍报 `generative raw call requires known live pointer
  provenance`。
* **调用点 extent 的常量偏移后缀**：`placeableRawExtent` 现在识别两种"后缀
  起点"写法（`array + k` 与 `&array[k]`），要求 `k + count <= 数组大小`。
  于是受检代码里 `slice_deferred(&local[1], 3u)`（`local[4]`）可编译并实跑读出
  `'b'`、`'d'`，而 `&local[3], 3u`（越界）仍报
  `slice extent must be the length of a slice or a counted suffix of a known
  array`。（`array + k` 写法在受检代码里另受 ModuleSafety 的指针算术规则限制，
  所以受检面用 `&array[k]`。）

**未做**：从**来源未知**的指针取偏移（`^const *(p+1u)`，p 是不透明形参）仍
拒绝——模型无法把偏移放进它看不见的分配，这需要 extent/对象尺寸的数据流
关联。`generative_lifetimes.py` 的"未建模"由 2 条降到 1 条（8 次运行计 8 条），
`slice_rebuild_regions.py` 反例 10 条。门禁：CTest 24/24，完整前端 gate 仍只
失败 `std2_consumers.py`，默认 Clang 有限差分 13/13，官方集合 1/14（0/6 库
示例）；原样 box_test O0 仍 108 错误、首个阻塞仍是 std2.h:396（本轮的裸来源
放宽不影响它，那是官方头文件自身的 static 契约）。证据
`build/implementation-baseline/raw-pointer-origin-evidence-v76.json`。

## 2026-10-14：AST77 模式只由编译指令选择；前端 gate 改为多核

用户重申既定模型：`#feature on safety` 已废弃，模式由编译命令直接指定，
单模块（单翻译单元）即可，且**每个函数都必须是 safe 的**。核对现状后语义
部分其实已经成立——无 directive 的普通 TU 在 safe langopt 下同样受检，
keyword-less 函数定义也按 safe 检查；真正的缺口是**指令不能单独使用**：
`-fcircle-safety` 只是 `-fmodule-safe` 的别名，而前端对任何 safety langopt
都强制要求 `-fmodule-safety-policy=`，于是连自包含的单模块也要先造一个工程
策略文件。

* `clang/lib/Frontend/FrontendAction.cpp`：删除"必须给出 policy"的诊断。
  策略文件变为可选，只在给出时交叉核对本模块与导入模块的模式，从不决定是否
  开启检查；"两种模式同时给出"仍报 `select one module mode`。
* `clang/include/clang/Options/Options.td`：仅帮助文本——`-fcircle-safety` /
  `-fmodule-safe` 描述为整个翻译单元或模块，policy 标注为可选。
* `tests/command_modes.py`：新增"指令单用"整组用例——普通单元、保留 directive
  的单元、命名模块和 `-fmodule-unsafe` 审计单元都不需要 policy；单模块走完
  precompile → 编译 → 链接 → 运行。
* `tools/test_frontend.py`：不再是串行 `run_regression` 序列，注册后由线程池
  并发执行（`--jobs`，默认 min(核数, 8)），输出按注册顺序汇报，失败仍使 gate
  失败；policy 检查块改为断言"指令单用即可检查"。

**实测**：`-fcircle-safety` 单用（无 policy）拒绝普通单元与命名模块里的裸指针
解引用；保留的 `#feature on safety` 不改变结论（同样拒绝）；`-fmodule-unsafe`
单用放行审计单元；两个模式同用报错；单模块 precompile/编译/链接/运行返回 0。
gate：并行 59 个回归 1:09.83 墙钟（串行约 4 分钟），日志与串行
`frontend-slice-v76.log` 逐字节一致（仅临时目录名、两处摘要文字与计时行不同），
唯一失败仍是 `std2_consumers.py`；CTest `-j 8` 24/24（34.45s）；默认 Clang
差分 13/13；官方集合 1/14（0/6 库示例）；补丁 99 文件无 fuzz 重放且字节一致。
原样 `box_test` O0 仍 108 错误、首个阻塞仍是 std2.h:396，带 policy 与只用指令
两种跑法结果相同。

**仍未完成**：去掉必需的 policy 后，同名导入模块的模式交叉核对只在给出 policy
时进行（跨模块契约是下一车道，用户已允许暂后）；`unsafe` 函数声明仍是整函数
退出检查的显式写法，本轮未改变其语义。证据
`build/implementation-baseline/directive-only-selection-evidence-v77.json`。

## 2026-10-14：AST79 借用与生命周期缺口逐条复核（generative 线两处真缺口关闭）

按用户表格第一行的顺序逐条实测五项缺口，结论是两项本就成立、两项是我们测试
写错、两项是真缺口（已关闭）：

* **对象尺寸与指针数据流（官方 `slice(self.data(), self.size())`）**：不是缺口。
  官方头文件在 968/972/1074/1758/1762/1787 处的该形态**全部位于 `unsafe { }`
  块内**，由 AST74 的"未检查代码声明 extent"规则接受；现在官方头文件 O0 检查
  已不再报任何 extent 错误。
* **未知来源指针的常量偏移（`^const *(p+1u)`）**：真缺口，且是
  `generative_lifetimes.py` 里 `unmodeled` 列表的最后一条。`src/FlowAnalysis.cpp`
  的常量偏移分支从"已知常量大小数组 + k"扩展到"来源为不透明外部指针根 + 非负
  常量 k"——这与 `^*p` 是同一种未检查声明，只是换了一个元素。运行期偏移
  `p+k`、反向偏移 `p-1u` 与 `array + size` 仍拒绝。
* **generative slice 的子区间与运行期长度**：属"按设计的拒绝"。受检调用者必须
  能放置 extent（同一 slice 的长度或已知数组的常量后缀，AST75/76），运行期长度
  由未检查代码放置——官方头文件正是在 `unsafe { }` 里这么做的。
* **调用点隐式可变接收者借用**：**前提是错的**。草案写明 `mut` 才建立可变上下文
  （"Or don't use it and bind shared borrows"），官方测试写
  `mut threads.push_back(...)`、`mut s.append(sv2)`、`vec^.push_back(1)`，普通
  左值本就不该隐式绑定可变接收者——这一条实现早已正确。官方头文件暴露出来的
  是**反方向**的真缺口：**已经持有借用的函数体必须能再借**。成员访问先把借用
  解引用成指代左值，于是 `push_back(self^, T t)` 里的 `self.grow()` 需要一次
  全新的 loan，而它要求可变上下文。`SemaOverload.cpp` 关闭：显式对象实参在
  "访问本就穿过某个借用、且接收者正是该借用类型"时直接绑定该借用（identity）。
* **老式双重解引用 `*(*b)`**：我们测试的拼写错误。官方 `box_test.cxx` 写的是
  `assert_eq(*p, 1337)`、`int^ x = mut *p;`、`assert_eq(**p, 1337)`，官方资料里
  没有 `*(*` 这种写法。运算符拼写的 `*` 会把 `operator*` 返回的借用**投影**到
  指代对象——这正是 `**p` 能工作而 `*(*b)` 不成立的原因。

**实测**：`p+1u` 的类值生成式返回在 8 种配置（local/PCM × O0/O2 ×
plain/ASan+UBSan）下编译并断言取值；`self.grow()`、`mut self.grow()`、
`(*self).grow()` 均可编译，普通左值裸调 `v.grow()`（只有可变重载时）仍拒绝，
共享借用无法洗白可变访问（`const V^ b; b.grow()` 与 `(*b).grow()` 都拒绝）。
`std2_consumers.py` 的消费者程序本身已无 Sema 错误（原 5 条全清），改为官方拼写
后报出的 20 条全部来自**官方头文件自身**，首项即 5 个字面量运算符：
`operator""sv2(char const*, size_t) -> string_view/static` 的返回值来自参数，而
标准明确规定字面量对象有静态存储期（`[lex.string]`：*Evaluating a
string-literal results in a string literal object with static storage duration*），
我们的 `static` 契约规则却只接受永久根。头文件其余清单按数量为：构造函数的
延迟初始化（30）、未分类全局存储（15）、未分类函数调用（13）、返回借用但未声明
生命周期契约的方法（10）、原始 delete（5）、指针算术（8）、不安全转换（3）、
原始分配（3）、未检查下标（2）等。

门禁：CTest `-j 8` 24/24（34.30s）；完整前端 gate 唯一失败仍是
`std2_consumers.py`（但失败原因已换成官方头文件自身）；默认 Clang 差分 13/13；
官方集合 1/14（0/6 库示例）；补丁 99 文件无 fuzz 重放。另记录一项行为：
**Sema 报错后检查器会停止检查该翻译单元**，因此错误计数依赖同单元内无关内容，
所有计数都是下界（这也解释了 box_test 108 与空 main 98 的差异）。证据
`build/implementation-baseline/row1-gap-audit-evidence-v79.json`。

**下一批按序**：①返回借用方法的接收者生命周期省略（官方 10 处，
`T^ f(self^)` 结果绑定到 `self`）；②字面量运算符的 `static` 契约
（官方 5 处，需要把义务延迟到调用点或承认字面量参数是永久存储）；③构造函数的
延迟初始化（30 处）；④未分类全局存储与函数调用（28 处）；⑤原始
alloc/delete/指针算术（16 处）。这些是"头文件端到端"这一项的真实内容。

## 2026-10-17：AST84 类值 slice 结果与字面量静态来源

本轮继续清理借用与生命周期线的两个真实阻塞：

* **slice 借用字段的类值结果**：`CircleClassLifetime.h` 的字段形状现在把
  `NativeSliceType` 以及具体化后的隐式 slice 记录都视为一个借用区域；该区域
  由 slice 句柄整体承载，元素类型不另立区域。因此
  `basic_string_view<T>` 的 `str(self const^)`、转换运算符和同一形状的自由
  函数/PCM 结果不再报 `non-static class-value result lifetimes are not yet
  modeled`。`SemaType.cpp` 也允许显式 `View/a` 签名从 slice 借用参数取区域，
  并继续拒绝两个来源之间的字段错配。
* **字面量运算符的静态来源**：用户定义字符串字面量的第一个 `const CharT*`
  参数现在携带 static lifetime 契约。字面量调用由 `[lex.string]` 的静态存储
  期满足；显式调用 `operator""x(local, n)` 则按静态参数契约拒绝。检查器同时
  从 `^*__slice_pointer(p, n)` 的数据指针恢复 slice 来源，并用 slice 自身的
  `~as_pointer`/`~length` 关系重建来源；这修复了上一轮引入的来源丢失，并保留
  了 `nested_borrows.py` 对受检代码中未放置 extent 的拒绝。

`tests/class_lifetime_elision.py` 现在覆盖 slice 字段、slice 转换、显式
`/a` 来源错误和字面量算子静态参数，48 个 local/PCM × O0/O2 ×
plain/ASan+UBSan 拒绝通过。完整前端 gate 目前仍只有 `std2_consumers.py`
失败；官方头文件的首个错误从上一轮的字面量 `static` 契约前移到
`std2.h:524`（`.format` 临时参数的 mutable global 失效保守检查）。CTest
`-j 8` 24/24、默认 Clang 差分 13/13、补丁 99 文件 `--check` 无 fuzz 且逐文件
重现均通过。剩余第一行缺口是官方头文件端到端的其余 20 条检查清单与复杂
generative 来源传播；拥有转移、析构和模块边界仍按用户表格继续推进，
当前不标记 100%。
