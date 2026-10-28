# Circle 对齐状态

目标：全面采用 Circle 语法并保持其安全语义；特性选择通过编译选项启用。
以官方库原样编译、链接、运行及反例拒绝作为兼容性验收。
类生命周期参数、成员包／反射、choice／match、切片和 interface／impl／dyn
均在实现范围内；此前仅用 concept 和自定义符号语法的方向由本目标取代。
基准：https://www.circle-lang.org/interop.html 和 https://safecpp.org/draft.html。
本表不是等价性声明。完整上游文档标题索引与原样源码编译诊断由
`python3 tools/circle_compatibility.py` 生成到 `build/circle-compatibility.json`；
索引中的 `unassessed` 不表示实现完成。

## 当前逐项清单与证据

当前机器清单及复现方式见 [compatibility/README.md](compatibility/README.md)。
92 项条目覆盖 New Circle 明列的 41 个独立 feature／research／edition 指令；
29 份历史文档的语义复核仍开放，不把 441 个标题计作完整特性清单。
`tools/compatibility_matrix.py` 绑定当前二进制、源码、清单、反例 oracle 与门禁日志，
过期验收会被拒绝。没有独立 Circle 二进制结果的条目明确记为 unavailable。

最新证据位于 `build/nested-aggregate-audit/features.json` 和 `features.md`：前端
112/112、CTest 26/26、默认 Clang 差分 13/13、104 文件无 fuzz 重放；
源码和二进制无漂移。官方正例 14 文件／54 配置通过；官方编译反例 19 个预期
规则拒绝、15 个未归属、0 崩溃。panic 14/16，另两次因本机未声明 `INT_MIN`
而未进入运行。新增修复包括数组借用转 slice、下标单次求值与宽整数边界、
abort panic、模板求值绑定重建及借用句柄 const／volatile 限定保留；本轮进一步
修复嵌套聚合父关系、普通临时聚合按值调用，以及借用句柄转移时的来源存活检查。
新增专项为 8 次本地／PCM 优化／sanitizer 执行和 33 类／132 次归属诊断拒绝。
原始 Circle stdlib 仍 0/6，完整兼容与发布未完成。下面保留历史推进记录，各阶段
失败数量和实现限制只代表当时版本。

## 固定的官方源码与原样兼容性验收

2026-10-12 对齐用户指定的 https://github.com/seanbaxter/circle，固定提交
`b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc`，保留完整原始仓库在
`downloads/circle-reference`。初次扫描覆盖 30 份 Markdown 文档、441 个标题。
官方 `stdlib` 目录的 6 个 `.cxx` 示例原样语法检查均未通过，诊断保存在上述报告。
成员参数包、反射属性、表达式包展开等仍是官方库的实际编译依赖。
不能通过定义虚假的 `__circle_build__` 宏或改写库源码宣布兼容。

仓库 `stdlib/README.md` 展示 tuple、variant、mdspan 的实现，不是完整安全标准库。
安全库另固定 https://github.com/cppalliance/safe-cpp 提交
`889685274438ca20344d4d9cb472e4392c4e35a9` 于 `downloads/safe-cpp-reference`。
原样 `libsafecxx/single-header/std2.h` 目前在 `#feature on safety`、
`typename... Ts+`、成员包、`[CharT; dyn]` 切片等接口处失败。
后续验收必须包含原样官方正例编译、链接、运行与官方反例按预期拒绝；
语法检查成功也不单独构成内存安全证明。

文档另引用的官方 mdspan 实现已固定为 https://github.com/seanbaxter/mdspan
`circle` 分支提交 `774a1f0c401144d88fdf4d655a70b777b879f4b4`，位于
`downloads/circle-mdspan-reference`。兼容性报告还直接检查完整 tuple、variant、
New Circle tuple 和 mdspan 头文件；不会把教学示例能编译等同于完整库兼容。

Circle 兼容方言必须在明确启用时保留原始语义。concept 可表示泛型约束，
但不能单独替代库中 interface/impl/dyn 的运行时类型擦除语义。

## 已落地的第一阶段

Circle 语法迁移入口为 `-fcircle-safety`（当前仍要求 C++20 命名模块及
`-fmodule-safety-policy=`）。函数安全效果可以写成 `safe`／`unsafe` 后缀；
重定位表达式使用 `rel value`；函数生命周期约束使用 `where a:b`。
成员函数支持按值 `self`、独占 `self^`、共享 `const self^`，以及原生借用的
`*loan` 和 `loan->member` 访问。旧写法保留用于既有回归，尚未完成全部语法迁移。
头文件内的 `#feature on safety` 仅断言命令行已开启安全检查；不能改变检查模式，
其他尚未实现的特性指令会报错。普通翻译单元的完整 Circle 安全模式仍未实现。

```cpp
export module circle_usage;
export struct Cell {
  unsigned value;
  unsigned read(const self^) safe { return self->value; }
  void write(self^, unsigned next) safe { self->value = next; }
};
export unsigned circle_example() safe {
  Cell cell{1u};
  cell.write(2u);
  const Cell^ loan = ^const cell;
  return (*loan).value;
}
```

原生 checked 模式接受 `T^`、`const T^`、`^owner`、`^const owner`。
二元 `a ^ b` 保持按位异或。未启用 checked 模式时保持 Clang 原有语法。
系统头文件保留 Clang Blocks 的 `^` 语法，避免改变旧式 C/C++ 接口。
借用表达式要求左值，shared 借用不能绑定可变引用。模板及 PCM 使用同一规则。

```cpp
export module example;
export unsigned example() {
  unsigned value = 1u;
  { unsigned^ loan = ^value; loan = 2u; }
  const unsigned^ loan = ^const value;
  struct Cell { unsigned value; Cell(unsigned n):value(n){} };
  Cell cell := void();
  cell := Cell(2u);
  unsigned copy = cell.value;
  cell := void();
  return loan + copy;
}
```

`T^` 是有独立规范类型身份的原生借用类型，`__is_same(T^, T&)` 为 false。
借用种类参与类型唯一化、函数类型、模板匹配、名称修饰和 PCM 序列化；
它不是 typedef、宏或只改变显示的属性。类型打印保留 `^`。
`^owner` 和 `^const owner` 分别保存为独立 UnaryOperator 操作，
不会改写为普通引用初始化或 static_cast。现有 CFG 借用分析直接追踪其所有者。

`auto loan = ^owner` 推导为原生独占借用；`auto loan = ^const owner`
推导为原生共享借用。也可以显式写 `auto^`。其他普通 auto 初始化遵循 C++ 按值读取规则：
`auto value = loan` 复制所指值；需要继续借用时写 `auto^` 或 `decltype(auto)`。
固定值类型和普通泛型值参数同样读取／复制所指值；显式 `T^` 参数保留借用。
decltype 在条件、逗号、赋值及前置增减等保留左值的表达式中保留借用种类。
按值 lambda 捕获读取／复制所指值，引用捕获保留借用并受到逃逸检查。
const 只限制直接对象状态；含可变引用的对象仍有修改能力，并按独占借用检查。
同一组重载同时接受 `T^` 和 `T&` 时，借用表达式及借用变量优先匹配
借用参数，普通所有者左值优先匹配普通引用参数。两种函数指针类型不能隐式混用。
原生类型及借用操作允许复用现有引用的存储布局、生命周期检查和机器代码路径；
这是后端表示，不会擦除前端或 PCM 中的原生类型身份。

回归入口：`python3 tests/native_borrows.py`，已接入 `tools/test_frontend.py`。

2026-10-11 验证范围（最终通过状态以发布报告为准）：原生借用专项测试通过，包含规范类型／别名身份、
auto／decltype／concept 约束、重载、模板、字段、constexpr、AST 操作、
跨 PCM 调用和 ASan/UBSan 执行，以及 21 个拒绝案例。
完整发布入口为 `tools/release_check.py --jobs 4`。历史入口包含 14 项子集 gate；
当前另增默认 Clang、上游 lit 和官方兼容 gate。`subset_status` 与
`full_compatibility_status` 分别报告子集与完整兼容，当前完整兼容未建立。
包括插件全部 24 项 CTest、原生完整回归、ASan/UBSan、TSan、模型检查、
官方源码补丁重放及示例构建／完整性／链接／执行。

## 消耗接收者

checked 接口的非静态 `&&` 方法消耗接收者，不增加关键字。例如
`unsigned take() && { return value; }`，可通过
`static_cast<Value&&>(owner).take()` 或临时对象调用。调用后 owner 进入 moved
状态；分支和异常合并保留这一状态。`&` 方法继续借用接收者。

不能通过 `T&`／`T^`、未知来源或子对象调用消耗方法，也不能在活跃借用下消耗
所有者。消耗方法必须非 const／volatile，实际所有者不能 pinned，并须有平凡
或经过审计的 moved-from 析构契约。消耗方法不能返回借用自身；转发消耗
`*this` 仅允许出现在消耗方法中，转发后不能再访问自身。借用携带对象消耗的是
持有者自身，不消耗其外部借用来源。

C++ 移动构造／移动赋值也不能通过引用参数、借用变量、借用返回或引用捕获偷偷
消耗调用者对象。只有移动构造、移动赋值或已检查的借用转移构造自身的源参数
拥有对应的转移权限；普通 `T&&` 参数仍是借用。可追溯的 rvalue 转发保留源权限。

这实现了调用处和方法体的 affine 接收者检查，仍沿用 C++ 的原存储和作用域
析构；不是 relocation 或部分移出。普通 C++ 及 unsafe 接口保留原有 `&&` 语义。
回归见 tests/consuming_receivers.py、tests/run.py 和 tests/native_borrows.py。

## 原生 relocation 和字段路径部分移出

`^^owner` 是独立 `UnaryOperator` 操作，产生拥有值，不调用复制／移动构造函数。
源对象生命周期结束，正常退出及异常展开均跳过其析构；结果仍按其拥有位置析构。
源必须是当前函数中的非 const／volatile、非 pinned 拥有值；借用、
lambda 捕获及未知来源不授予 relocation 权限。
整数、enum 与浮点值也支持 `^^`、`:=` 和延迟初始化；标量按值参数可以转移及恢复。

`^^owner.field` 和 `^^owner.child.field` 可移出拥有的字段路径。路径经过的父对象包含自定义析构、基类、union、外部借用
或 pinned 存储的父对象不支持此操作；`no_unique_address` 字段也拒绝。移出后不能
读取缺失字段或整个父对象，其他字段仍可使用、借用和继续移出。析构只执行仍在的
字段，并在异常路径保持同样的状态。完整路径区分重复类型中相同的字段声明；每个
子树都有独立来源。借用另一个独立字段不会阻止移出当前字段，借用父节点则冻结
整个子树。移出后仍可借用其余字段。位域和重叠字段不授予拥有路径权限。

当前原生 AST 格式为 45（此项早期实现使用 40）。tests/native_relocation.py 在 O0/O2 + ASan/UBSan 验证确切
析构次数、未调用移动构造、分支／循环／异常、跨 PCM、模板、借用持有者及字段借用，
包含 18 个拒绝案例。普通赋值不能恢复已经 relocation 的存储。

## 原生销毁并替换

`owner := fresh_value` 是独立的二元 AST 操作，结果为 void。目标必须是当前函数中
非 const／volatile、非 pinned 的局部拥有值，右侧必须是同类型的新拥有值。
不调用复制、移动构造或赋值运算符。先完成右侧构造，再析构目标剩余的旧值，
最后转移新值并恢复完整的初始化状态。因此可以恢复 `^^` 后的源或部分移出的对象。
右侧构造失败保留旧值；旧析构抛出时清理新值并禁止异常处理器读取已结束的目标。
活跃目标借用、自借用的新值、引用参数及 lambda 捕获均不能绕过拥有权限。

`owner.field := fresh_value` 和嵌套路径可单独恢复拥有的字段，`owner.field := void()`
则结束该字段的生命周期。父对象须已初始化，且没有自定义析构、基类、union、外部
借用或重叠字段。独立字段的借用互不阻塞；目标字段或整个父对象的借用阻止替换。
字段析构抛出时，目标字段失效，其他字段仍保留其生命周期与清理责任。整个子树
转移／销毁会失效所有后代；恢复子树会恢复全部后代，不能在已结束的父节点下
单独恢复一个子字段。

`owner := void()` 结束局部对象生命周期，并保持未初始化状态。它也可用于 const、
pinned、部分移出及可能已失效的局部对象；只析构实际仍在的值。存在活跃借用时拒绝。
`T owner := void()` 声明延迟初始化的局部拥有值，不调用默认构造；后续 `:=` 完成
初始化才允许读取。声明使用同一符号，未初始化及失败构造的路径不调用析构。

tests/native_replacement.py 覆盖跨 PCM、模板、循环、构造失败、抛出析构、字段与
完整对象恢复、pinned／const 销毁和延迟初始化，在 O0/O2 + ASan/UBSan 检查实际
分配与确切析构次数，包含 24 个拒绝案例。tests/native_nested_places.py 另覆盖
跨 PCM、重复字段声明、深层借用、子树恢复、参数／构造委托／异常清理及 10 个拒绝案例。

## 拥有参数的析构 ABI

checked safe 模块定义的非平凡记录使用被调用端析构其按值参数的 ABI；该信息保存在
原生记录 AST 和 PCM 中。参数可以整体／直接字段 `^^` 转移，也可以 `:=` 替换／
销毁。调用端只在尚未进入函数而后续实参构造失败时清理该参数；进入函数后交由
被调用端的 whole／field live 标志控制。构造委托、虚调用和安全函数指针沿用同一责任。
这使用真实的参数存储和析构责任，不转换成普通引用参数，也不调用移动构造替代 `^^`。

tests/native_parameters.py 在 O0/O2 + ASan/UBSan 检查确切析构次数、跨 PCM、模板、
异常、整体／字段转移、替换、显式销毁、构造委托、虚／间接调用及 6 个拒绝案例。
旧 C++ 类型保留其 ABI；需要调用端析构的非平凡参数不能进行原生拥有转移。
外部 C++ 代码按值传递这些原生记录时必须理解此 ABI，不能直接沿用旧 ABI 的声明。

## 原生按值 self

成员函数可用 `^^` 标记显式拥有对象参数：`Resource into(^^ Resource self)`。
调用写为 `(^^owner).into()` 或 `Resource(...).into()`；命名接收者必须明确转移，
不隐式调用复制／移动构造。`self` 是真实的按值记录参数，沿用原生拥有参数 ABI；
函数结束时析构剩余字段，`return ^^self` 转移整个对象并跳过源析构。
可以在方法中移出字段，普通参数、模板、操作符及函数指针均使用相同的值参数规则。
原生 AST 保留显式对象参数身份及拥有标记，类型为记录值，不转换成 `T&`／`T&&`。

tests/native_self.py 覆盖跨 PCM、模板、字段转移、操作符、间接调用、抛出路径、
确切析构次数及 6 个拒绝案例，O0/O2 + ASan/UBSan。不能使用隐式 `this`、引用
形态的 self 或借用接收者。虚显式对象方法仍依循 C++ 的拒绝规则。

## 原生函数生命周期绑定

原生 `T^/a` 与 `f/(a,b where a:b)` 已接入函数签名；类型别名同样支持 Circle 绑定。outlives 传递闭包、区域相等归并和名字规范化参与类型身份、名称修饰、重声明、虚函数契约和 PCM。每个返回来源必须符合关系；调用方冻结所有可能来源，独占借用与临时对象规则继续生效。单输入省略与显式单区域回调类型一致。原生类型／关系专项见 `tests/native_lifetimes.py`，当前 32 个拒绝案例在 O0/O2 + ASan/UBSan 下执行。

## 第一类借用值与局部 T+ 投影开发模式

`-fcircle-borrow-values` 与 `-fcircle-safety` 配合使用，生成独立的借用值
类型，保留指针值存储、复制和显式解引用语义。该模式仍处于开发阶段。
共享复制、独占移入/移出、数组存储、函数/模板生命周期、借用类箭头与
字段借用返回已通过 O0/O2、PCM 和 ASan/UBSan 测试。

T+/Ts+ 标记保存在 AST 中。简单拥有记录支持逐字段来源状态、字段重新绑定、
字段单独 relocation、隐式且平凡的默认聚合复制/移动赋值、嵌套对象和
跨模块实例化。分支合流保留各字段的可能来源，移出单个字段不再清空
兄弟字段的借用。借用聚合对象同时记录其存储与内部数据的寿命。

命名类生命周期、完整类型实参投影/提升、未知借用接收者的字段写回、
自定义赋值效果、借用槽数组逐元素更新及自动方法接收者借用仍未完成。
`include/std2/std2.h` 是 interface/impl 改为 concept 的开发适配版；见下节
的当前状态。遗留的空 `interface send/sync` 声明已随这一轮 concept 改写删除，
它们与 slice.h 中的 `send`/`sync` concept 同名且无人使用；其余源码未改动。

## 2026-10-12 原生 slice、安全限定符与表达式算子

验收口径按官方库探针的方式：把该头文件本身当作翻译单元编译
`-std=c++20 -fcircle-safety -fcircle-borrow-values -fmodule-safety-policy=… -fsyntax-only -x c++ include/std2/std2.h`。
该口径下的错误从 **269 条降到 47 条**。新增的 Circle 语义：

- 普通翻译单元的安全模式：`-fcircle-safety` 现在可用于不属于任何命名模块的
  TU，但只在该源码确实写了 `#feature on safety` 时才检查（Circle 把安全
  限定在开启它的文件）。指令本身仍只是断言，不会自行开启检查；插件层
  （`-add-plugin module-safety`）保持只接受命名模块的契约。检查效果不会
  标记系统头内的声明——否则标准库的函数类型会被加上 `safe_function`
  属性，破坏普通的模板实参推导。
- 第一类借用模型下的隐式接收者借用：`recv.method()` 在 `self^`/`const self^`
  形参为借用值时自动形成 `^recv`/`^const recv`；隐式 `operator->` 调用（普通
  重载决议之外的路径）同样形成借用接收者。`T^` 到 `const T^` 是限定的隐式
  转换，正如 `T*` 到 `const T*`。
- `unsafe { ... }` 不再开启词法作用域（Circle 明确要求声明在其后可见），
  行内成员定义中缓存的 `: unsafe member(...)` 初始化器与普通路径一致。
- 函数后缀 `safe`/`unsafe` 现在可写在尾置返回类型之前（`noexcept safe -> T`）。
- `safe(e)` 作为 requires 原子（`requires(safe(T()))`）。
- `operator[]` 的多参数形式在检查模式下是扩展而非错误；`&.`/`&->` 对已经是
  地址的接收者（裸指针、原生借用）直接命名其引用对象。

## 2026-10-13 match 运行语义修正

固定 Circle 文档规定 `lo ... hi` 为半开区间，等价于
`lo <= operand && operand < hi`。已修正旧实现包含上界的问题，并保留界值
的 C++ 字面量类型，避免窄操作数将界值截断。共享／可变 `^payload` 模式
现在绑定原生借用类型，保持 const 和载荷所有权。专项验证包含 constexpr、
两个 checked 模块的 PCM、实际 O0/O2 和 ASan/UBSan。

依赖类型 match 已加入原生 AST 与 PCM 保留，在实例化时重建绑定并检查
具体操作数。`tests/dependent_match.py` 覆盖 choice、范围、bool、嵌套借用、
constexpr 和非平凡载荷的返回／析构／异常清理，实际 O0/O2 + ASan/UBSan。
AST 格式为 45。完整模式语法、签名中的表达式名称修饰、返回借用来源推导
及原样官方整文件验收仍未完成；下面的历史说明不构成完整特性验证。

## 2026-10-12 choice 与 match

`choice` 类型与其 `match` 表达式已可用（不再拒绝），语义如下：

- 布局：每个 choice 记录获得编译器生成的 `__circle_choice_tag`（无符号标签）
  与 `__circle_choice_payload`（每个备选一个字段的联合）。备选在解析备选列表
  后立即生成，因此 choice 自身的成员函数可以构造与匹配自己的值。
- 构造：`.alt` / `.alt(payload)` 按备选名推断 choice 类型（先查外层声明上下文，
  再查已注册的 choice 类型），形成聚合值并设置标签与载荷字段。Circle 的
  “由期望类型推断”被限制为这两种来源；两个来源都没有时给出诊断。
- `match(operand) [-> T] { pattern => expr; ... }` 降级为：求值操作数一次
  （按左值引用或按值绑定，取决于操作数是否左值）、逐个测试标签的嵌套条件
  表达式，臂体在仅该臂可见的语句表达式作用域内求值。模式支持 `.alt`、
  `.alt(binding)`、`.alt(^binding)`、`.alt(_)`、`_`、`default` 与
  `true`/`false`。`.alt(binding)` 以 `__rel_read` 把载荷读入拥有局部变量，
  `.alt(^binding)` 绑定载荷的借用；`_`/`default` 必须是最后一个臂。
  不返回的臂（`[[noreturn]]` 调用）按 bottom 类型强制为该臂的结果类型。
- 检查器：编译器生成的 choice 存储联合、choice 值与 match 语句表达式在
  检查器中有对应豁免（choice 的活动备选由标签自身跟踪，不由 union 活跃成员
  规则跟踪）；`__rel_read` 等编译器的内建按名字受信任。

上述语义是**受限实现**：没有为 choice 生成按活动备选析构的析构函数
（生成的记录使用平凡析构），没有穷尽性证明，模式也不支持绑定以外的高级形式
（OR 模式、范围、嵌套子模式）。`tests` 未新增专项回归，验证用的是本轮的
checker 端到端小例。
- 原生动态切片：`[T; dyn]^` 现在是携带地址与元素数的一等借用值
  （`BorrowValueType(NativeSliceType)`），`*slice` 命名其元素序列，`s[i]` 是
  带边界检查的 `__builtin_circle_slice_index`，`~length`、`~as_pointer`
  分别是元素数与元素地址。`__slice_pointer(p,n)`、`__rel_read(p)`、
  `__rel_write(p,v)` 作为编译器内建（`Builtins.td` + 自定义类型检查）提供，
  其契约由检查器作为编译器原语信任。

- `unsafe` 类型限定符：声明说明符、指针／引用声明符（`T* unsafe p_`）、
  成员初始化器（`: unsafe m_()`）四处均可书写。按提案语义，unsafe 对象在
  safe 上下文中照常可用，因此该限定符本身不产生检查。函数后缀 `unsafe`
  的既有语义不变（它要求 `AllowUnsafeQualifier` 为假，不会被误当作限定符）。
- 后缀 trait `x~name` 与类型 trait `T~name`：`is_trivially_destructible`、
  `is_trivially_copyable` 复用 clang 的 `TypeTraitExpr`；`is_send`/`is_sync`
  按标量／枚举判定。
- 表达式算子：`cpy`（复制读取）、`drp`（结束生命周期）、`mut`（可变使用标
  记，保持操作数）、`addr`（取址）、后缀 `^`（命名 place）、`&.`/`&->`
  （不安全 place 成员访问）。`rel` 的前缀与后缀形式都可用。
- 类生命周期实参与成员限定符：`string_view/static` 这类类生命周期实参在
  类模板特化上解析到主模板的 `safecpp.native.class.lifetimes:` 注解；
  `/static` 作为内建生命周期不需要类生命周期参数；尾置返回类型上的限定符
  （`-> T^/a`）现在会并入函数声明的生命周期契约。
- `= trivial` 特化成员等价为 `= default`。
- 检查模式下的用户定义字面量后缀不再要求下划线前缀。

带 `^^`/按值 `self` 的消费接收者允许平凡复制类型的左值接收者（按值复制而
非转移），这与 Copy 类型的语义一致；非平凡记录仍要求显式 `^^` 或临时对象。

该口径当时仍未通过的 33 条错误（成员包与 tuple、编译器提供的 `string_constant`、
借用值成员访问的常量求值、`operator rel(T)` 与 `optional::take_if` 级联）在
2026-10-13 全部关闭，见下节。切片仍无地址／长度代码生成；其类型与元素访问
已可用。

## 2026-10-13 `std2.h` 作为翻译单元编译成功

同一验收口径下 `include/std2/std2.h` 现在 **0 error、exit 0** 通过，重复运行
结果一致；剩余 3 条警告来自库自身的 `printf("%.*s", …)` 格式检查
（`size_type` 而非 `int`），不是前端的诊断。自 47 条起新增或修正的语义：

- 借用的常量求值：`*borrow` 现在先读借用的值（左值到右值转换）再解引用，
  与指针一致。于是 `source_location` 的 `constexpr` 访问器在求值器中与
  未知指针参数走同一条"静默不成立"路径，不再被判为"永不产生常量表达式"。
- 切片借用与 `string_constant`：字面量是编译器提供的 `string_constant<CharT>`
  值（同一"地址＋长度"聚合），转换仍是精确匹配；切片借用则由**目标类自己的
  构造函数**接收（`basic_string_view(const [C; dyn]^)`）。借用到*类*的隐式
  转换因此放行给用户定义转换，借用到指针、引用或标量仍然拒绝——否则借用的
  地址会被当成值读走。实例化时折叠值从切片的两个成员重建。
  `panic`、`panic_bounds`、`println`、`operator""sv2` 等因此可用，且
  `println(sc.text())` 选中的是 `string_view` 重载。
- 原生 tuple：`(A,B)` 类型（含嵌套、`(Args...,)` 成员包与 `T+`/`Ts+` 标记）、
  `.N` 成员访问、`.[:]` 整元组、`.(...)` 调用与 `(a, b,)` 尾随逗号均已解析；
  括号列表在目标类型是生成元组记录时构成元组值（列表即逗号表达式，元素为其
  操作数）。`.N` 由词法合成一个 pp-number（`tup.1.[:]` 读作 `.1.`），因此
  元素序号与随后的 `.[:]` 从同一 token 拆出。括号形状在实参位置参与
  "声明还是表达式"的消歧，试探性解析不再泄漏诊断。
- `rel` 后缀：`value rel.member` 与 `value rel.(args)` 先重定位再访问；
  `rel args...` 把前缀运算并入包展开的模式（`rel arg0, rel arg1, …`）。
- `operator rel(T)`：写成"到重定位目标"的转换声明，并补上源拼写省略的空参数
  参数表；构造函数的 leading `/(where F: static, Args...: static)`
  种类约束仍缺调用点模型，当前明确拒绝该声明。
- `T~is_send`/`T~is_sync` 改为 `TypeTraitExpr`（`UTT_IsSend`/`UTT_IsSync`），
  于是依赖类型时保持值依赖、可参与折叠表达式；新增 `__is_lambda`。
- 库属性族 `[[unsafe::…]]`、`[[safety::…]]`、`[[circle::…]]` 被识别为声明契约
  并转成 `safecpp.*` 注解：`sync(true|false)`、`send(true|false)`、
  `drop_only(T)`、`panic(N)`、`unwrap`、`niche_zero`、`no_unique_address_any`。
  没有参数的 `[[unsafe::send]]` 是肯定声明；检查器据此把该类自己的存储视为
  已分类，不再对表示方式（如 `std::atomic` 内部的 `_Atomic`）报"未检查存储"。
- 检查器：模板中值依赖的全局读延迟到实例化判定（实例化体会被再次访问）；
  生成的聚合若含依赖成员则不取布局。
- 按值参数的检查 ABI：checked 编译定义的记录（命名模块、普通 TU 及其包含的
  头文件）使用被调用端析构 ABI，因此 `forget(rel self)` 这类按值参数重定位
  在头文件里也可用；`module;` 全局模块片段文本包含的 legacy 头记录仍保留
  C++ ABI，其按值参数重定位继续被拒绝（native_parameters 的反例不变）。
- `match` 的解析状态改为栈，嵌套 match（`(match(…) { … })` 作为臂体）不再
  丢失外层臂列表。

### 2026-10-13 切片与 choice 的代码生成：消费者程序可编译、链接、运行

上一节的验收只看"`std2.h` 作为翻译单元能否通过"。本轮把它推到**消费者**
一侧：用该头文件写普通程序，编译、链接并运行。之前只有语法层通过与
`-fsyntax-only`；真正生成代码时会崩溃或产出错误值。本轮修正的语义：

- 切片借用是"地址＋元素数"的一对：`ASTContext::getTypeInfoImpl`、
  `CodeGenTypes`、`Sema::BuildUnaryOp`（`*slice` 命名元素序列）与
  `CGExprScalar::EmitNativeBorrow`、`CGExpr::EmitUnaryOpLValue` 一致地按
  16 字节对处理，因此 `(*s)~length`、`(*s)~as_pointer` 与 `string_view`
  的 `p_` 成员在运行期取到真实长度和地址，而不是把借用本身当地址读。
  于是 `std2::string_view("hi")`、`println(sv)`、`sv.size()` 全部正确。
- 编译器提供的类值（"地址＋长度"聚合）在代码生成时按它持有的聚合写入：
  `CK_NoOp` 转换 + `InitListExpr` 且两者存储大小相同的场合，目标地址按源
  聚合类型重新解释后整体写回，不再按目标类的字段逐一下标——后者会把
  `_text.__circle_len` 写到对象之外（越界 8 字节），这正是 `sv.size()`
  读出垃圾值的原因。
- 实例化一个 choice 模板会重新创建生成成员的注解，`isImplicit` 标记消失。
  于是 `describeChoice`、`payloadField`（`storageMarked`）不再要求注解是
  隐式的——只按编译器保留的注解文本识别。此前 `optional<int>` 的
  `payloadField` 返回空，构造出的联合初始化列表缺少
  `setInitializedFieldInUnion`，载荷永远不被写入（常量折叠成 `undef`，
  运行期则 `unwrap()` 读出 0）。
- `.alt(payload)` 由**期望类型**推断 choice 特化：`PreferredType` 只在代码
  补全时启用，因此解析器为初始化器、直接初始化的首个实参和 `return` 语句
  各记录一次期望类型（按位置匹配，越过 `{`），Sema 侧再先请求该特化的
  实例化。没有期望类型又落在非依赖上下文时给出诊断，而不是构造一个
  "模板自身类型"的值（后者会在求大小时无限递归）。
- choice 重定位与匹配：`match` 绑定把载荷从生成的存储联合中移出，检查器
  的"部分重定位要求无自定义析构的拥有路径"不再拒绝编译器自己的 choice
  存储；`rel t` 与 `.alt(binding)` 因此可用。
- 模板实例化保留编译器提供的转换：`TransformInitializer` /
  `TransformImplicitCastExpr` 不再剥掉类型不同的 `CK_NoOp` 转换，也不再把
  构造函数转换折叠成它的实参；`TransformInitListExpr` 重建的列表保留语义
  形式的类型。否则函数模板里的 `panic("…")` 会把切片记录当成
  `basic_string_view` 的实参列表来初始化（"2 arguments provided"）。
- 恒不返回的调用在 `?:` 中按 bottom 类型处理：`CXXCheckConditionalOperands`
  现在接受"另一侧是 `[[noreturn]]` 调用"的 void 操作数，并把它按另一侧的
  类型记录。match 降级出的条件链因此能在实例化后重建。
- choice 的默认构造函数：定义为 `default` 的备选若不带载荷，前端为该 choice
  生成一个默认构造函数把标签写成该备选的序号，于是
  `std2::optional<int> n;` 的 `is_none()` 是 `true`（此前标签不确定，
  匹配会走到 trap）。检查器把该生成的构造函数与生成的析构函数同等地视为
  编译器所有。

结论：`include/std2/std2.h` 本身仍 **0 error**，且用它写的消费者程序现在
能编译、链接、运行并给出正确结果（字面量／`string_view`／`string` 追加／
`optional` 的 `.some`、`is_some`、`is_none`、`unwrap`／用户 choice 的
`match`／`vector` 的 `push_back` 与带边界检查的 `[]`／`box`）。完整回归仍为
14/14 必需 gate、24/24 CTest 与 `tools/test_frontend.py` 全量通过，补丁
无 fuzz 重放一致。


### 2026-10-13（续）match 模式、自定义重定位与线程契约求值

上一节把验收推到消费者程序；这一节关闭当时列出的全部剩余项：

- **match 模式**。模式现在是一棵树：`.alt`（可带载荷模式或绑定）、`_`/
  `default`、`true`/`false`、值（`0`）、范围（`lo...hi`）与 `|` 连接的多
  个模式。范围写成 `lo...hi`（`1...9`）：词法器把 `1...9` 读成*一个*
  pp-number，因此范围的端点从该 token 的拼写里读出、而不是重新词法。
  降级仍然是一串条件表达式，但每个臂的测试由模式递归生成：嵌套模式
  （`.wraps(.holds(v))`）在载荷的*位置*上继续测试，`|` 把各分支的测试
  用 `||` 合并。绑定按外层到内层的顺序初始化（外层先移出）。穷尽性检查
  按顶层备选、bool 的两个值与"必须有匹配任何值的臂"分别要求；另外所有
  臂的测试会在运行前再测一次，没有任何臂匹配时故障（否则链尾那个臂会
  替一个没有匹配的值作数）。`|` 的每个分支必须绑定相同的名字。
- **备选载荷的自定义 relocation**。`choice` 的 match 绑定与 `__rel_read`
  走的就是 `rel`，因此载荷类型声明的重定位算子会被调用（见下一条）。
- **用户定义的重定位构造函数**。定义里写 `operator rel(T)` 即声明重定位
  算子：它是对目标类型的转换声明（解析器补上源拼写省略的空参数表），
  声明上带编译器注解。`rel x`、`include/std2` 的 `__rel_read`、match 绑定
  与 `replace` 都通过它构造目标值，源对象不析构、只清掉 drop 标志；
  常量求值在类型带自定义重定位时不再当作逐字节拷贝。
- **`f.(args)` 元组展开**。`.(…)` 现在走 `ActOnCircleTupledCall`：当且仅当
  唯一实参的类型是生成的元组记录时，把它展开成该元组的元素（元素按序传入，
  `.[:]` 的整元组也照此展开）；其余情况仍是"以这些值为实参的调用"。
- **依赖参数的 Send/Sync 求值**。`[[unsafe::send(T~is_send)]]` 的实参在
  声明处依赖时被记录在注解上，实例化时替换并按实例求值：前端为每个
  实例记录"契约成立"（`safecpp.thread.send`/`sync`）或"契约不成立"
  （`safecpp.unsend`/`unsync`），检查器先读这个结论，读不到才回退到模式上
  写的、尚未替换的声明（模式本身照旧接受）。`T~is_send`/`T~is_sync` 也
  按同一条规则求值：标量与枚举为真，记录读它声明的契约，否则看字段与基类。
- **整条切片的 `cpy`／`rel` 与借用的借用**。切片借用就是"地址＋元素数"的
  一对，整条切片的 `cpy`/`rel` 读写这一对（源不再被销毁）；`T^^` 现在
  合法，是"借用句柄自身占据的存储"，`*handle` 读回句柄。判断"借用指向的
  是不是切片记录"的地方（`ASTContext` 的大小、`CodeGenTypes` 的表示、
  借用与解引用的代码生成）都改为直接看被指类型本身，不再穿透一层借用。

回归：`tests/choice_patterns.py`（模式与 6 个拒绝）、
`tests/relocation_operators.py`（`rel`、match 绑定与 choice 载荷的自定义
重定位）、`tests/tuple_call.py`、`tests/nested_borrows.py`、
`tests/conditional_contracts.py`（按实例求值的契约与 trait）已接入
`tools/test_frontend.py`。

上述关闭方式是**分阶段**的，以下语义仍不完整：

- `/(where L: static)` 的调用点种类约束仍缺模型；现在明确拒绝此声明，
  不再静默丢弃约束。普通函数借用绑定的 `/(a,b where a:b)` 保留现有实现。
- 元组值只在目标类型是生成元组记录时成立；`f.(t)` 现在展开元组实参（见
  下节），但 `f.(a, b)` 仍是"以这两个值为实参的调用"，多个元组不会各自展开；
  `.[:]` 只是"整元组"占位；`expr...` 对非包模式的接受是延迟展开，元素个数到
  实例化才确定；元组仍无原生迭代协议与代码生成。
- `operator rel(T)` 的*正体*已实现（见下节）：重定位、match 绑定与
  choice 备选载荷都经它构造目标值；仍未实现的是把重定位声明成构造函数形
  （`T(T&&) rel`）的拼写。
- `unsafe::send/sync` 的依赖参数按实例化求值（见下节）；`is_send`/`is_sync`
  读取定义里声明的契约、字段与基类，未声明的表示（例如裸指针）仍判为不可跨
  线程传递。
- 切片借用的类型、`sizeof` 与代码生成统一为"地址＋元素数"的一对；整条
  切片借用的 `cpy`／`rel` 以及"借用的借用"（`T^^`，读取句柄自身的存储）
  也已实现（见下节）。

## 四项统一验收与兼容边界

四项的当前实现、统一门禁与证据入口见 [FOUR-PILLARS.md](FOUR-PILLARS.md)。
本节取代前面历史批次中“仅解析”“尚无 CodeGen”及按记录来源决定参数析构 ABI
的旧状态；具体通过状态以该门禁生成的报告为准。

- 区域身份、替换和泛型投影按选定的 Circle 兼容扩展实现，包含词法外层捕获、
  遮蔽、四点类参数方差及嵌套关联投影；无法唯一恢复来源的投影不能提供安全证明。
- `operator rel(T)` 与 `relocate(T rhs)` 共用重定位查询。用户钩子、default／
  trivial／delete、递归子对象和激活 choice 载荷均进入代码生成；后者的源参数
  保留所有权并在构造结束清理剩余子对象。`locate` 按用户确认指这两个参考入口。
- 旧 C++ 按值参数按函数契约决定析构责任，显式 legacy 包装验证双向调用、
  间接调用、返回和异常清理。checked 参数用 `Legacy unsafe value` 审计旧析构。
  尚未引入草案的三个新调用约定及自动函数指针适配。
- choice 支持 OR 共同绑定、结构匹配后的 guard、嵌套 choice／tuple 的组合
  穷尽性；guard 不证明覆盖。tuple 值推导、单次求值的点调用／整包调用及
  `.[:] ...` 的异构参数包遍历有运行矩阵；未新增普通异构 ranged-for。
- slice 地址与长度共同生成、复制、传参及返回。`~string` 支持模板实例化和
  内建／cv／指针／限定类型解析；其文本不是跨编译器稳定的类型身份。

尚未执行整个 Circle 语言的逐项兼容清单及独立 Circle 二进制差分，亦未引入
Rust trait／GAT 语言体系。普通 C++ 移动继续使用移动构造，显式重定位使用
本仓库的所有权转移和条件析构规则。
