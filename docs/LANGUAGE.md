# 语言与运行库

本文集中公开接口与当前支持边界；实现规则见 [SAFETY.md](SAFETY.md)，
测试和兼容缺口见 [VALIDATION.md](VALIDATION.md)。扩展以 Circle／Safe C++ 为参考，
采用本仓库的 Circle 兼容扩展范围，不等同于完整 Rust HRTB／GAT。

## 编译模式

`-fcircle-safety`（别名 `-fmodule-safe`）检查整个 C++20 翻译单元或命名模块。
`-fmodule-unsafe` 用于保持传统行为的 unsafe 单元；两个选项互斥。
关闭扩展时以保持上游 Clang 行为为目标，有限差分测试不证明全部兼容。

safe 单元中的函数默认受检查，可使用函数后缀 `safe` 和显式 `unsafe_fn`。
`unsafe { ... }` 允许受审计的底层操作；它不改变所在函数的对外分类。
其中定义的 lambda／函数体会进入自己的安全上下文，不继承 unsafe 权限。
unsafe 单元不能声明 safe 函数。

`#feature on safety` 只断言命令已开启检查，不能切换模式。
`-fmodule-safety-policy=FILE` 是可选的工程一致性校验，用来核对接口、分区、实现
和导入 PCM 的模式，不能代替开启检查的选项。原生扩展由解析器处理，不依靠宏。

插件入口接受 `safe`、`unsafe` 和可选 `policy=FILE`；使用
`include/module_safety.h` 的兼容属性／宏。插件与加载它的 Clang 必须 ABI 匹配，
插件本身不提供原生借用类型及其 PCM 表示。

## 借用、移动与存储

`T^` 为独占借用，`const T^` 为共享借用，`^owner`／`^const owner` 创建借用。
它们有独立的规范类型身份，参与模板、名称修饰和 PCM，并非 C++ 引用的 typedef。
`*loan` 和 `loan->member` 访问目标；二元 `a ^ b` 仍是异或。
共享借用允许复制；独占借用的复制、父借用冲突、过期来源及局部存储逃逸被拒绝。

`rel value`／`^^owner` 转移拥有值并结束源的相应生命周期；转移后不能继续读取。
这不同于普通 C++ 移动后仍然执行作用域析构的模型。
`target := value` 先构造右侧再销毁旧值、转移新值；构造失败保留旧值。
`target := void()` 销毁并退休存储；`T target := void()` 延迟初始化。
普通赋值不能恢复已经结束生命周期的位置，成功的 `:=` 可恢复适用的存储状态。

拥有字段以完整字段路径区分，父节点借用冻结子树，独立分支可分别使用。
部分移出和字段替换要求布局及析构责任可追踪；存在自定义析构、基类、union、
重叠存储等情况时不能自动套用普通聚合规则。
普通数组／嵌套聚合的再借用须由每个重叠来源授权，后续初始化不能使前面的临时
借用失效。复杂构造和间接存储使用专属契约，不能靠根来源相同获得访问许可。

非静态 `&&` 方法消耗整个接收者，异常路径也禁止后续使用；需要有效的 moved-from
析构契约。普通 `T&&` 参数仍是借用，不会自动授予对调用者对象的消耗权限。
原生 `^^ T self` 为按值拥有的显式对象参数，使用同一套参数存储和清理规则。

## 生命周期与高阶关系

```cpp
const unsigned^/b select/(a,b where a:b)(
    const unsigned^/a longer, const unsigned^/b shorter, bool first) {
  if (first) return ^const longer;
  return ^const shorter;
}
```

`/a` 指定区域，`/(a,b where a:b)` 引入绑定，`a:b` 表示 a 至少与 b 一样长。
绑定按作用域及身份解析；关系闭包、等价区域及规范化共同决定契约身份。
单个适用借用输入可省略结果来源；多个潜在来源需显式契约，不猜测运行期分支。

嵌套回调的绑定作用域独立，可词法捕获外层区域并正确处理同名遮蔽。
共享借用支持有证明的协变缩短，可变位置保持不变；嵌套函数参数组合逆变。
重声明、覆盖和 impl 的身份检查与回调转换的方向性替换分开处理。

显式类区域、`T+` 类型携带区域及实例化字段按模板参数身份映射；类参数方差按
字段和回调结构组合并求固定点。关联别名链、偏特化、继承、成员别名模板、包元素
及包索引投影接受相应正反例检查。重复、重排、嵌套和静态区域不能靠字段名称推测。
无法证明唯一映射或替换关系时拒绝相应借用操作。

兼容属性 `SAFETY_RETURNS_BORROW`、`SAFETY_STORES_BORROW`、`SAFETY_LIFETIME`、
`SAFETY_RETURNS_LIFETIME` 和 `SAFETY_STORES_LIFETIME` 声明返回／保存来源。
属性不授权悬空引用；函数体、调用点及具体模板实例化都要验证其契约。
原生量化绑定不能与旧的返回来源属性混用。

safe 函数类型保留安全效果和生命周期契约。丢失安全效果的普通函数指针只能在
unsafe 中调用，unsafe 函数不能隐式升级为安全指针，安全间接调用检查空指针。
契约随 PCM 保存，导入不能擦除来源和写入约束。

## 重定位与旧 C++ ABI

`operator rel(T)` 和 `relocate(T rhs)` 共用 Sema／CodeGen 策略：用户钩子、
平凡／默认／删除形式、逐成员处理或适用的旧 C++ 移动／复制及源析构。
同一类型同时声明两种不同钩子时拒绝重定位。choice 只转移激活载荷；phantom
字段保留类型约束但不参与物理存储重定位。重定位期间逸出的异常终止进程。
`relocate` 构造钩子在结束时清理未移出的源子对象，不参与普通构造重载。

非平凡按值参数的析构责任属于函数契约，直接、间接调用及 PCM 必须一致。
已验收的 macOS arm64 上，checked 函数负责参数清理；legacy 函数保留平台的
调用者清理规则，不能转走调用者仍须析构的参数。
旧 C++ 对象操作可通过 `Legacy unsafe value` 显式审计，跨边界用 `unsafe_fn`
包装和 checked 函数桥接。新调用约定及所有平台的自动 ABI 适配不在此保证范围。

## choice、tuple 和 slice

choice 的构造、重定位、匹配及析构保持激活载荷身份。OR 模式各分支必须绑定相同
名称和类型；guard 失败继续后续分支，guard 自身不构成穷尽证明。
嵌套 choice／tuple 用组合模式矩阵检查，不能用各列覆盖代替整个乘积覆盖。

tuple 的 `f.(tuple)` 和 `f(tuple.[:] ...)` 对展开表达式求值一次。
推导 tuple 字面量用尾随逗号 `(a,b,)`，已知 tuple 目标也接受 `(a,b)`。
异构元素通过包展开及折叠遍历；这不提供任意异构 tuple 的普通 ranged-for 协议。

slice 用地址和元素数共同传递；复制、转移、参数和结果保留两者及来源。
固定数组可转换为适用的 slice，未知长度、丢弃 cv 和重复独占权限被拒绝。
下标固定接收者并对索引求值一次，先检查负值和未窄化的宽整数，越界执行 abort
panic。会重绑或失效捕获借用的索引表达式仍保守拒绝。
借用后写的 const／volatile 句柄限定保留到类型与 PCM；共享弱化不复制独占权限。

`T~string` 在模板实例化后得到具体类型名；依赖的 `.format(...)` 延后求值。
文本是本编译器的打印结果，不是跨编译器稳定的类型身份。

## 运行库索引

| 模块 | 主要接口与限制 |
| --- | --- |
| `safety` | 检查型算术、标量 array／vector、move、callable 和标量签名 function |
| `safety_conversions` | `into<T>` 要求全类型范围无损；`try_into<T>` 检查具体值，失败时 value 初始化为零；`checked_into<T>` 失败 panic |
| `safety_borrows` | `borrowed_vector<T,Owner>` 保留 Owner 来源；元素存储借用存活时禁止扩容 |
| `safety_mutable_borrows` | 检查型工厂建立独占／共享借用；元素须无异常移动和销毁 |
| `safety_lifetimes` | `with_borrow` 返回独立值／void，`map_borrow` 可按契约返回 Owner 的借用 |
| `safety_ownership` | pin_box／pin_region／pin_ref，as_ref／as_mut、投影及受限 take；pinned 对象不能被移址 |
| `safety_threads` | run_thread、scoped_thread、share_thread、parallel_share；mutex 的异常路径仍释放锁 |
| `safety_atomic` | 最大 64 位整数、bool、指针原子及五种内存序；非法顺序拒绝，指针原子不证明目标存活或 ABA 安全 |
| `safety_coroutines` | 不保存外部借用的拥有型标量 generator；一般异步任务不在支持范围 |

Send／Sync 递归考虑字段、基类、数组和实际可变能力；const 句柄不等于只读目标。
`SAFETY_UNSAFE_IMPL_SEND/SYNC` 是库作者的审计义务，不能代替同步实现。
Pin 的对象在析构之前保持地址稳定，句柄借用存活时不能转移或销毁它；take 只允许
适用的非 pinned 类型且满足无异常移动和来源要求。
数值转换不会自动改写 C++ 隐式转换，也不为内建标量添加 `.into()` 成员语法。

完整的可编译模块示例见下文；更多运行程序见 `examples/` 和 `tests/`。

## 模块示例

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
