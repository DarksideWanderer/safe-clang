# 四项统一验收

本批以已选定的 **Circle 兼容扩展** 为范围。区域捕获、方差和关联投影的规则见
[安全架构](SAFETY-ARCHITECTURE.md)。四项共用同一固定版本验收；报告中的源码、
二进制和日志摘要均须与当前版本一致，旧记录不能代替当前验收。

2026-10-27 最新固定版本报告为 **passed**：前端 **112/112**、CTest **26/26**、
原样官方正例 **14 文件／54 配置**、默认 Clang 有限差分 **13/13**、
**104 文件**无 fuzz 补丁重放，原生／插件构建与格式检查均通过。
验收前后源码／二进制摘要一致，证据见
[acceptance.json](build/nested-aggregate-audit/final-acceptance/acceptance.json)。
本轮修复数组／嵌套聚合的再借用父关系、临时聚合按值实参及转移时的来源检查。
新增专项为 8 次本地／PCM、O0／O2 普通及 ASan/UBSan 执行，33 类／132 次
带诊断归属的拒绝，覆盖重复独占、父借用冻结、过期来源、转移后重用及实参副作用。
前一轮修复 slice 转换、求值、边界、模板和 cv 限定；其官方 vector 中间失败保留于
`build/slice-runtime-audit/acceptance/`，不计入通过。

首批合并验收的 109 项前端／103 文件重放，以及随后 111 项前端／103 文件重放
均为历史记录。兼容清单的开放缺口见 [compatibility/README.md](compatibility/README.md)，
不由四项回归代替；本批也不宣称整个 Circle 语言完成。

```sh
python3 tools/accept_four_pillars.py --jobs 4
```

命令先构建原生编译器和插件，再运行全部前端回归、CTest、独立 Clang 22.1.2
默认模式差分、无 fuzz 补丁重放及差异格式检查。测试前后核对补丁、清单、原生
源码、共享检查器、测试脚本和二进制摘要；源码或二进制在验收中发生变化即失败。
同时校验固定 Circle／Safe C++ 参考仓库的提交、干净状态和参考文档摘要。
已构建时可用 `--skip-build`。所有门禁保留日志，失败不会写成通过。

| 项目 | 实现与验收要点 | 主要回归 |
| --- | --- | --- |
| 区域关系闭环 | 身份与方向性替换共用区域表示；重声明、覆盖、impl、转换、直接／间接调用保留各自效果要求；聚合再借用保留已证明的父关系 | `region_relation_entries.py`、`aggregate_reborrow_parents.py` |
| 通用高阶关系 | 独立绑定作用域、词法捕获和遮蔽、包替换、共享协变、可变不变、嵌套参数逆变；类参数按固定点求方差 | `higher_ranked_relation_algebra.py`、`outer_region_captures.py`、`class_parameter_variance.py`、`captured_callable_values.py` |
| 泛型投影 | 按模板参数身份映射显式区域、类型携带区域、实例化字段、关联别名及包元素；拒绝不唯一的来源证明 | `generic_region_projection.py`、`multi_region_class_values.py`、`nested_class_values.py` |
| 运行语义 | 重定位策略与析构次数、旧 C++ 对象互操作、组合模式和穷尽性、tuple 遍历与调用、slice 地址／长度、实例化后的类型名 | `runtime_semantics.py`、`legacy_value_abi.py`，以及既有 relocation、choice、tuple、slice 专项 |

## 重定位与旧 C++ 边界

采用固定 Safe C++ 草案的 `operator rel(T)`。`rel source` 按同一策略查询执行：

- 用户定义的 operator 负责生成目标值；源对象退出已初始化状态。
- `= trivial` 选择表示复制；`= delete` 禁止重定位。
- `= default` 及隐式策略：安全析构类型平凡重定位，聚合按子对象递归，其余类型
  通过适用的旧 C++ 移动／复制构造，再析构源对象。
- 兼容 New Circle 的隐式策略：无用户析构和移动构造的记录也逐成员重定位，
  普通构造函数不改变这项规则，避免隐式 C++ 移动复制拥有资源的子对象。
- choice 仅对激活载荷应用子对象策略。重定位期间逸出的异常终止进程。

策略查询由 Sema 和 CodeGen 共用，删除及访问控制在生成代码前检查。字段、基类、
数组和 choice 载荷不能各自退回无条件字节复制；隐式调用的用户钩子、移动／复制
构造与源析构仍须通过函数安全分类。固定 Safe C++ 草案定义
`operator rel(T)`；New Circle 另定义 `relocate(T rhs)` 构造钩子。后者的初始化列表
构造目标，`rhs` 文本上按值、内部按引用传递，并在构造结束时清理未转移的源子对象。
该钩子不参与普通构造重载，也不抑制隐式默认构造；`relocate source` 读取同一重定位
策略。此前清单中的 `locate` 按用户确认指这套重定位语义。
显式 `relocate(T rhs)=default` 按 New Circle 规则优先选择无用户析构／移动构造
类型的逐成员重定位，否则使用适用的普通移动／复制构造并清理源对象。一个类型
同时声明两种不同重定位钩子时拒绝重定位，避免任意选取其一。
phantom 字段保留类型及区域约束，但不具有运行时存储，不参与子对象重定位查询。
例如，phantom 字段类型删除了重定位，不会单独使其包装类的物理表示不可重定位。

非平凡按值参数的析构责任属于**函数契约**。在本批验证的 macOS arm64 ABI 中，
checked 函数负责清理其按值参数，legacy 函数保留平台的调用者清理规则。
直接与间接调用均读取函数类型的契约，PCM 保留该区别。旧 C++ 析构没有 checked
契约时，按值参数用 `Legacy unsafe value` 显式审计其对象操作和退出清理；省略审计
仍拒绝隐式调用未分类的析构函数。对外提供普通 C++ 入口时，
使用显式 `unsafe_fn` 包装，并将参数移动到 checked 函数：

```cpp
Legacy checked_identity(Legacy unsafe value) safe {
  unsafe { return rel value; }
}
unsafe_fn Legacy legacy_entry(Legacy value) {
  return checked_identity(static_cast<Legacy&&>(value));
}
```

legacy 函数不能用 `rel` 转走调用者仍负责析构的非平凡按值参数；即使该记录
最初在 checked 代码中定义，也按当前函数契约判断。

`legacy_value_abi.py` 用独立上游 Clang 编译调用方和被调对象，核对双向边界、
间接调用、返回与异常的移动、析构和资源释放次数。草案提出的
`__legacy`／`__relocate`／`__unified` 新调用约定及自动指针适配不属于本批语言入口。

## 组合模式、tuple、slice 与类型名

OR 模式各分支必须绑定相同名称和类型；初始化只读取命中的分支。guard 在结构
匹配并绑定后求值，失败继续后续分支；模板的 guard 保留到实例化，PCM 保存相同
结构，guard 本身不证明穷尽。嵌套 choice 与 tuple
通过模式矩阵检查整体组合，不能用各列分别覆盖来证明整个乘积覆盖。

tuple 的 `f.(tuple)` 与模板中的 `f(tuple.[:] ...)` 对被展开表达式求值一次。
为保留已有 C++ 逗号表达式，推导 tuple 字面量使用尾随逗号 `(a,b,)`；已有 tuple
目标类型也接受 `(a,b)`。构造函数实参列表仍按普通参数列表处理。
异构元素通过 `.[:] ...` 展开后可按 C++ 参数包的折叠顺序遍历；空包不调用元素操作。
这不是新增异构 tuple 的普通 ranged-for 协议。单次求值绑定仍保留原借用来源。
模板 tuple 字面量先展开表达式参数包，再按实际元素重建结构类型；空包和嵌套包
使用相同路径，不能把依赖类型的初始化列表遗留给 CodeGen。

slice 借用以地址和元素数共同传递；复制、重定位、参数与返回必须保留两者。
固定数组及其借用转换为 slice 时构造同一地址／长度对，保留来源和父借用关系；
未知数组长度、丢弃 cv、未经许可的可变借用和重复独占权限均拒绝。
slice 下标先固定接收者的地址／长度，再对索引求值一次；检查有符号负值和未经
窄化的宽整数，越界使用与原生数组相同的 abort panic。模板中非依赖下标会重建
绑定，PCM 保留相同语义。会重绑或使捕获的 slice 借用失效的索引表达式保守拒绝。
`T^ const^`／`T^ volatile^` 的句柄限定保留到类型与 PCM；const 句柄可建立同一
referent 的共享借用，不能复制出独占外层权限，也不能借此覆盖只读句柄。
`T~string` 在模板实例化后生成具体类型名，支持内建、cv／指针和限定类型解析。
其文本是本编译器的类型打印结果，不作为跨编译器稳定类型身份。
依赖参数的字符串 `.format(...)` 保留到模板实例化后再求值，避免在定义时把依赖的
`T~string` 当作具体字符串。

新增运行矩阵覆盖本地／PCM、O0／O2、普通与 ASan/UBSan；既有完整回归仍须通过。
本次新增运行语义专项执行 8 次本地／PCM 正例、12 次 noexcept 异常终止检查和
34 个拒绝用例；旧 ABI 专项另执行 8 次独立上游 Clang 互操作程序。
这些执行均在本机 macOS arm64 上验收。
这份四项验收不等同于整个 Circle 语言完成，也不替代独立 Circle 二进制对照。

后续数组／slice 专项在该固定版本额外执行 8 次本地／PCM、O0／O2、普通及
ASan/UBSan 正例，24 次负下标／宽整数 panic，46 个类型／权限／来源拒绝，
4 次原样官方越界程序及其 abort handler。原样官方 panic 总检查为 14/16，
另两次因 `divide_overflow.cxx` 在本机未声明 `INT_MIN` 而未进入运行；不计作通过。
