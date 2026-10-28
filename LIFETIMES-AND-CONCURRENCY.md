# 生命周期、Pin 与并发接口

## 原生函数生命周期

checked 函数与函数类型别名可以使用 Circle 生命周期绑定：

```cpp
const unsigned^/b select/(a,b where a:b)(
    const unsigned^/a longer, const unsigned^/b shorter, bool first) {
  if (first) return ^const longer;
  return ^const shorter;
}
using Callback = const unsigned^/a /(a)(const unsigned^/a);
```

`/a` 绑定借用的区域；`/(a,b where a:b)` 声明量化区域，`where` 后的 `a:b` 要求 a outlive b。名字只在本次函数签名中有效，所有带绑定签名中的原生借用输入和输出必须显式指明区域。原生绑定不与旧的返回来源属性混用。

编译器计算 outlives 的传递闭包，把互相 outlive 的区域归并为同一区域，再按参数／结果中的首次使用规范化名字。重命名、绑定声明顺序、重复／传递冗余边不改变类型；改变有效关系会改变函数类型。绑定和关系参加类型唯一化、名称修饰、重声明及虚函数契约检查，并写入 PCM。单输入省略得到同样的规范表示，因此 `identity(const T^) -> const T^` 与显式单区域接口可以使用同一种回调类型。

函数体每次返回都要证明实际来源 outlive 结果区域。调用方保守保留全部可能来源的借用，直到结果最后一次使用；不会因选择分支而猜测来源。不存在输入到结果的关系时，函数只能返回永久存储。无捕获普通／泛型 lambda 的单输入借用会使用同样的省略和 safe 回调类型；转换生成的 invoker 委托检查实际 operator 与具体特化，不能把空 AST stub 当作用户函数，也不能隐藏 unsafe 实现或悬空返回。函数指针在每次调用中可以绑定不同的实际局部生命周期，仍拒绝临时对象逃逸、源对象提前修改及独占借用别名。`tests/native_lifetimes.py` 验证类型关系和跨 PCM 的 O0/O2 + ASan/UBSan 执行。

当前范围是函数原生借用接口。记录值的原生生命周期实参、嵌套泛型生命周期投影、完整高阶函数子类型／方差仍未实现；它们不能用现有参数来源集合或运行库 region 标签替代。函数类型转换当前要求契约相同，避免丢失未检查的关系。

## 命名生命周期

参数的 `SAFETY_LIFETIME(name)` 引入函数内的借用区域；`SAFETY_RETURNS_LIFETIME(name)` 和 `SAFETY_STORES_LIFETIME(name)` 分别约束返回来源和构造存储来源。同名参数共同约束结果；每次具体模板实例化都会验证函数体，属性不能使局部对象的引用变得有效。

```cpp
template<class T> SAFETY_RETURNS_LIFETIME(a)
const T& choose(bool first,
    SAFETY_LIFETIME(a) const T& left,
    SAFETY_LIFETIME(a) const T& right) {
  if (first) return left;
  return right;
}
```

这个结果依赖两个参数的生命周期交集。调用者不能在仍使用结果时修改任一可能的来源，也不能把未延长生命周期的临时对象作为持久借用来源。标签只在当前函数内命名；原生函数类型将其规范化为参数位置集合并写入 PCM。重声明必须保持来源集合，标签重命名不改变集合。

`safety_lifetimes` 提供 `std2::with_borrow<Callback>(owner)` 和 `std2::map_borrow<Callback>(owner)`。前者没有返回借用契约，只允许独立拥有值或 void 结果；后者允许返回与 Owner 关联的引用／借用对象。回调在具体实例化时接受检查，不能通过返回局部引用绕过约束。

这些接口支持模板和高阶编译期回调；原生前端还支持在不同局部生命周期上复用同一个带返回借用契约的函数指针。并不等于已经实现 Rust 的所有 `for<'a>`、GAT、trait-object 生命周期及方差规则。原生返回来源使用规范化参数集合；超过 31 个参数的联合来源同样参与类型身份、名称修饰和 PCM 序列化。不支持的关系不能当作已经验证的契约。

## 原生借用的生命周期省略

checked 自由函数返回原生 `T^`，且只有一个引用输入时，可以省略返回来源属性：

```cpp
const unsigned^ identity(const unsigned^ value) {
  return ^const value;
}
```

同样的省略适用于返回原生借用的 `safe_function` 函数类型别名；同一个回调可以在不同调用中绑定不同局部存储。

省略产生的是函数类型中的来源契约，跨 PCM 调用仍使用该契约检查冻结、作用域和临时对象逃逸。函数体必须证明每个返回值来自该输入，不能返回局部存储。多个引用输入、可能携带借用的按值记录输入和成员函数仍需显式契约；不猜测来源。普通 C++ `T&` 返回值保留现有显式契约要求。

## 固定地址拥有与借用

checked 非静态 `&&` 方法提供消耗接收者：调用即使抛异常也消耗调用方的整个拥有对象，
后续读取或再次调用被拒绝。`&` 方法只借用。通过引用、原生 `^` 借用、子对象或
未知来源消耗被拒绝；非平凡析构必须具有独立审计的 moved-from 契约。消耗
`*this` 需要当前方法同样为消耗方法；转发后不能再访问接收者。消耗借用携带
对象不会转移其外部存储的拥有权。整体独立拥有值可以通过完整赋值重新初始化。
这不是部分移出或 relocation，C++ 作用域析构仍执行。

`safety_ownership`：

- `pin_box<T>::make(args...)` 在堆上原地构造，参数可为拥有型对象。构造验证发生在 safe 上下文，实际分配在运行库 unsafe 边界。借用型 T 必须只存储自己的 pinned 借用。
- `pin_region<T,Owner>(owner,args...)` 可同时保存自引用及显式 Owner 的借用；构造存储契约只允许第一个 Owner 参数，其他参数不能被借用保存。整个 Owner 区域保持独占借用。
- `pin_ref<T>` 提供栈上借用；只读实例支持复制，独占实例只能移动。地址敏感类型必须声明 `SAFETY_PINNED`，这会禁止对象在借用结束后重新获得移动能力。
- `as_ref`／`as_mut` 创建再借用；`project<Callback>`／`project_mut<Callback>` 通过已检查的返回来源契约投影。
- `pin_box::reset(args...)` 先构造替换对象；构造失败保留旧对象，成功后析构并释放旧对象。为避免参数析构访问已经释放的旧存储，替换参数必须独立拥有，不允许借用型参数。
- `pin_box::take()` 只允许安全、无异常的移动；pinned 或没有有效返回借用契约的借用对象被拒绝。析构在释放存储之前发生。

Pin 句柄的移动不移动对象；句柄的借用存活时不能移动或销毁它。Send/Sync 递归取决于目标和 Owner，递归拥有结构通过循环检测终止。Pin 保证涉及直到析构的存储有效性，参见 [Rust Pin 契约](https://doc.rust-lang.org/std/pin/)。

## 原子操作

`safety_atomic` 支持最大 64 位整数、bool 和原始指针。`atomic_ptr<T>` 是 `atomic<T*>` 的别名。顺序以模板参数传入，例如：

```cpp
flag.store<std2::memory_order::release>(1u);
auto ready = flag.load<std2::memory_order::acquire>();
auto result = flag.compare_exchange<std2::memory_order::acq_rel>(1u,2u);
```

提供 relaxed、acquire、release、acq_rel、seq_cst；默认 seq_cst。load/wait 拒绝 release/acq_rel，store 拒绝 acquire/acq_rel，CAS 失败顺序拒绝 release/acq_rel。单独给 CAS 成功顺序时，失败顺序自动去掉 release 部分。强/弱 CAS 返回 `{exchanged, previous}`，弱 CAS 可以伪失败。

提供 exchange、fetch_add/sub、整数及 bool 的 fetch_and/or/xor、wait、notify_one/all、is_lock_free 和 atomic_fence。bool 不提供算术操作。整数原子算术具有定义的回绕；指针算术不承诺结果指向有效对象。原子指针不拥有目标、不能证明回收或消除 ABA，safe 代码仍不能解引用原始指针。锁自由程度由目标标准库决定。相关前置条件见 [C++ 原子操作](https://eel.is/c++draft/atomics.types.operations)及[指针原子操作](https://eel.is/c++draft/atomics.types.pointer)。

## 系统验证和证明边界

`tests/lifecycle_system.py` 从独立 PCM 实例化模板，在 O0/O2 + ASan/UBSan 下验证命名区域、交集、嵌套异常、部分构造、Pin 构造失败和借用容器复制失败回滚，并检查错误来源、逃逸和重声明反例。

`tests/ownership_concurrency.py` 验证 Pin 移动／投影／取出、Owner 冻结、递归 Send/Sync、原子 RMW/CAS、release/acquire 消息传递、等待通知、布尔和指针操作；同一套用例在 ASan/UBSan 和 TSan 下运行。运行库仍依赖 C++ 析构、分配、pthread 和标准原子实现。通过这些用例不构成所有执行交错、所有异常路径或所有 unsafe 代码的形式化证明。
