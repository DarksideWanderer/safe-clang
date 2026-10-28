# unsafe 运行库审计契约

这里列出 safe 接口依赖的实现义务及执行验证。用户自定义 unsafe 实现也必须满足对应义务；给类型写 unsafe Send/Sync 属性本身不构成证明。

| 模块 | unsafe 实现必须保持的不变量 | 验证入口 |
| --- | --- | --- |
| safety | 长度/容量界限、分配对齐、整数操作先检查后执行、移动后唯一拥有、空回调不可调用 | runtime.py：ASan/UBSan 和 14 种 panic；conversions.py |
| safety_conversions | 失败不执行越界转换；成功精确保留数值；输出始终初始化 | conversions.py：65,536 个输入及浮点边界；prove_conversions.py：210 个模型条件 |
| safety_borrows | 元素借用在 Owner 内；复制／析构安全效果独立验证；复制失败回滚新存储；析构不抛；只改内部存储的函数不修改借用目标 | borrowed_containers.py；lifecycle_system.py：实际复制抛异常及析构计数 |
| safety_mutable_borrows | Owner 独占区域；只通过检查后的工厂创建借用；元素引用存活时不扩容；工厂／移动／析构安全效果独立验证；搬移和销毁不抛异常 | mutable_borrows.py：增长、移动及冲突反例 |
| safety_ownership | 原地构造、对象存活期间不移址、析构先于释放、析构安全效果独立验证、使用全局限定的分配／释放、句柄转移后唯一拥有；有外部借用时保留 Owner | ownership_concurrency.py；lifecycle_system.py：构造失败/清理/投影/取出/临时参数失效 |
| safety_threads | callback 在 safe 上下文验证；线程结束前不释放参数/结果；每条失败路径处理已启动线程；mutex 对象回调独立验证且异常路径解锁 | threads.py：ASan/UBSan、TSan、异常回调及能力反例 |
| safety_atomic | 每次操作使用活着的原子存储；非法顺序不能进入标准库；不返回对内部存储的引用；指针原子不授予解引用能力 | ownership_concurrency.py：两套 sanitizer、CAS 顺序矩阵、发布/等待/通知、指针拒绝 |
| safety_lifetimes | 无 unsafe 实现；具体回调与返回来源由检查器验证 | lifecycle_system.py：独立 PCM、O0/O2、借用逃逸及错误来源拒绝 |

测试不证明标准库、分配器、pthread 或 LLVM 本身正确，也不证明任意用户编写的无锁算法正确。指针回收、ABA 防护及未建模的 FFI 契约仍由相关 unsafe 实现承担。当前没有将全部运行库转换成形式化程序逻辑并完成证明；不要把测试表当作该证明。

| 模块 | unsafe 实现必须保持的不变量 | 验证入口 |
| --- | --- | --- |
| safety_coroutines | 单一帧拥有句柄、移动后清空、只恢复活着的未完成帧、只产出标量、不保存外部借用、析构只销毁一次帧；自定义 promise/suspend 标记需独立审计 | coroutines.py |
| safety_regions | 不擦除实际所有者；共享目标协变、独占目标不变、区域缩短不能扩张实际存储生命周期；没有 unsafe 实现 | regions.py |

追加的独立边界回归见 tests/runtime_boundaries.py，覆盖 unsafe 复制／析构／对象回调拒绝以及不调用类专属分配器的实际 ASan/UBSan 执行。
