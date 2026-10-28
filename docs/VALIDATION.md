# 验证与支持范围

当前主要验收环境为 macOS arm64、LLVM／Clang 22.1.2、C++20。
原生扩展和插件共享检查器；插件 ABI 必须与宿主匹配。完整 Circle 兼容尚未建立。
本文件合并验收流程与支持边界，逐特性元数据见 [compatibility/](../compatibility/README.md)。

## 统一回归

先完成 [构建](../README.md) 和固定参考依赖准备，然后运行：

```sh
python3 tools/accept_four_pillars.py --jobs 4
```

该入口构建原生编译器及插件，运行全部前端回归、CTest、独立 Clang 默认模式
差分、无 fuzz 补丁重放和差异格式检查。`--skip-build` 仅用于已构建输入。
源码、原生文件、固定参考提交、二进制及日志均须绑定同一快照，过程中变化即失败。
失败日志保留，非零退出不能记为通过。

| 工作项 | 检查内容 | 主要回归 |
| --- | --- | --- |
| 区域关系闭环 | 重声明、覆盖、impl、转换、直接／间接调用统一身份与来源；聚合再借用权限 | region_relation_entries、aggregate_reborrow_parents |
| 通用高阶关系 | 独立绑定、外层捕获、替换、共享协变、可变不变、嵌套逆变、类参数方差 | higher_ranked_relation_algebra、outer_region_captures、class_parameter_variance、captured_callable_values |
| 泛型投影 | 显式／携带区域、实例化字段、关联别名、嵌套及包元素身份 | generic_region_projection、multi_region_class_values、nested_class_values |
| 运行语义 | operator rel／relocate、析构责任、旧 ABI、choice／tuple、slice 和类型名 | runtime_semantics、legacy_value_abi、relocation_operators、tuple_*、array_slice_conversions |

表中名称对应 `tests/` 下的文件或文件组。合法程序执行、非法程序拒绝、诊断归属、
跨 PCM 及 O0／O2／sanitizer 是不同检查维度，不能互相替代。
反例必须因预期规则失败；崩溃、无关解析错误和任意非零返回不算有效拒绝。

## 历史证据与当前复现

2026-10-27 的固定开发快照通过前端 **112/112**、CTest **26/26**、官方正例
**14 文件／54 配置**、默认 Clang 有限差分 **13/13**、**104 文件**无 fuzz 重放。
嵌套聚合专项通过 8 次执行及 33 类／132 次带诊断归属的拒绝。

这些是历史快照结果；构建日志不随源码仓库分发，整理后的源码和工具变动不能
自动继承旧报告。新克隆需要重新构建验收。13 个差分案例不证明完全兼容普通 Clang，
四项范围验收也不证明完整 Circle 兼容或所有 safe 程序无 UB。

兼容矩阵还记录原始 Circle stdlib 0/6、官方 panic 14/16、34 个编译反例中
19 个已归属／15 个未归属等缺口。完整目录和复现命令见
[兼容清单](../compatibility/README.md)，不把未执行、崩溃或缺少依赖当作通过。

## 其他验证入口

```sh
python3 tools/test_frontend.py --jobs 4
ctest --test-dir build --output-on-failure
python3 tests/prove_conversions.py
python3 tests/prove_union_model.py
python3 tools/check_lean.py
python3 tools/ub_inventory.py --check
python3 examples/segment-tree/verify.py
```

证明入口分别依赖 Z3、固定 Lean 工具链或本地 N4861 输入；依赖准备见
[PUBLISHING.md](PUBLISHING.md)。形式化模型、有限状态检查和 sanitizer 的边界见
[SAFETY.md](SAFETY.md)，没有运行的检查不能据文件存在就记为完成。

`python3 tools/release_check.py --jobs 4` 还冻结二进制摘要，依次运行独立 Clang、
上游 lit、原样官方输入、证明和示例等强制门禁，并要求完整官方兼容门禁。
当前完整兼容未建立，该最终门禁不能称为已通过。`subset_status` 和
`full_compatibility_status` 必须分别解读，禁止用部分通过绕开失败。

## 模块产物与发布检查

`tools/build_modules.py` 分析依赖，记录源、头文件、编译器和产物摘要，失败时
不发布半套 PCM。成功构建用符号链接切换独立代目录；首次迁移普通目录期间应停止
消费者读取。用 `python3 tools/verify_build.py OUTPUT` 核对，链接时只解析一次
真实路径并使用同一代产物。摘要用于变化检测，不能抵御同时篡改内容和清单。

所有模块生产者须走同一受检查构建链。手工替换 PCM、绕过检查器编译实现或篡改
策略不能作为安全证据。unsafe／FFI、堆分配、pthread、标准原子及系统库属于信任边界。

文档精简或发布前运行：

```sh
python3 tests/documentation.py
python3 tests/public_source_export.py
python3 tools/prepare_public_source.py
git diff --check
```

源码发布及许可证范围见 [PUBLISHING.md](PUBLISHING.md)。二进制分发须另核对实际
打包组件、对应源码和许可义务；源码整理不等于生产环境或全部语言兼容验收。
