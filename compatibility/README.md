# Circle 兼容清单与固定版本证据

本目录将特性范围、实现入口和实际执行结果分开记录。清单仍在补全；目前不能据此
宣布完整 Circle 兼容或完成发布。

- `circle-features.json`：92 个特性条目，含固定 New Circle 文档中的全部 41 个
  feature／research／edition 指令。每项记录参考提交与位置、实现符号、正反例入口、
  独立对照状态和缺口。实现了 safety 模式下的某个语法，不等于实现了同名的独立指令。
- `safe-cpp-negatives.json`：34 个原样官方编译反例的源码摘要和人工归属规则，含上游
  已停用的 `mutex3` 探索输入。仅首个带位置的错误符合已审核的规则与行号才记为验证；
  构造约束拒绝还须出现约束失败的说明。崩溃、无关前置错误和普通非零退出不计通过。
- 历史文档的语义拆分、未实现特性的专属反例及独立 Circle 二进制对照仍开放。
  机器报告保留 `inventory_complete=false` 和 `fully_compatible=false`；文档标题数量
  只用于覆盖检查，不作为语言特性数或完成度。

复现当前版本：

```sh
python3 tools/accept_four_pillars.py --jobs 4 --output build/nested-aggregate-audit/final-acceptance
python3 tools/circle_compatibility.py --output build/nested-aggregate-audit/original-sources.json
python3 tools/compatibility_matrix.py \
  --acceptance build/nested-aggregate-audit/final-acceptance/acceptance.json \
  --official-evidence build/nested-aggregate-audit/original-sources.json \
  --output build/nested-aggregate-audit/features.json \
  --markdown build/nested-aggregate-audit/features.md
```

报告生成时核对当前编译器、插件、共享检查器、展开的原生源码、测试、清单、oracle
和门禁日志摘要。原样官方输入的报告也须来自当前源码／二进制。缺失或过期证据使
绑定失败，不自动复用历史通过。未传 `--acceptance` 时，只能生成 `not_executed` 清单。
完整清单门禁可单独执行，目前会以非零退出，保留待补项目：

```sh
python3 tools/compatibility_matrix.py --require-complete-inventory
```

2026-10-27 的本批结果见 `build/nested-aggregate-audit/`：

- 原生／插件构建、前端 **112/112**、CTest **26/26**、默认 Clang 差分 **13/13**、
  **104 文件**无 fuzz 补丁重放全部通过；测试前后源码及二进制摘要不变。
- 官方正例 **14 文件／54 配置**在全量回归中通过；另一次原样官方探针的 O0／O2
  编译、链接和程序断言也通过。
- 34 个官方编译反例中 **19** 个归属预期规则，**15** 个仍未归属（含停用探索输入），
  编译器崩溃 **0**，意外接受 **0**。
- 官方 panic 输入 **14/16** 次检查通过；剩余两次是 `divide_overflow.cxx` 的
  O0／O2 构建，在本机因未声明 `INT_MIN` 而失败，没有进入运行。
- 原始 Circle `stdlib` 示例仍 **0/6**，没有将它们计作兼容通过。

本轮修复嵌套独占借用聚合的父关系丢失。数组、嵌套结构、复制／转移及已知来源
的再借用保留祖先；每个来源重叠的聚合元素都必须授权对应父关系，条件分支取交集。
普通临时聚合直接／间接按值调用按其真实组成值检查权限；具有 phantom／间接存储、
union、基类或自定义析构的复杂类型继续使用既有专属契约。数组后续初始化表达式
不能使此前的临时借用失效，先修改再借用的合法顺序仍通过。
同时补上借用句柄转移前的 referent 存活检查，拒绝把过期句柄作为调用实参转移。
`tests/aggregate_reborrow_parents.py` 通过 **8** 次本地／PCM、O0／O2、普通及
ASan/UBSan 运行，以及 **33 类／132 次**带诊断归属的拒绝检查。

前一轮补齐固定数组借用 `^array` 到 slice 的地址／长度构造，并保留父借用。
slice 下标接收者及索引只求值一次，先检查负值和未窄化的宽整数，越界使用 abort
panic；模板中的非依赖下标可重新建立求值绑定。解析器此前丢失借用后写的
const／volatile，现在限定会保留到类型及 PCM，并拒绝只读句柄写入和 volatile
读取。共享弱化保留同一 referent，不能复制独占外层权限。
专项通过 8 次本地／PCM、O0／O2、普通及 ASan/UBSan 运行、24 次边界 panic、
46 个拒绝用例和 4 次原样官方越界程序运行；官方 vector 用例也已恢复通过。

`build/slice-runtime-audit/acceptance/` 保留前一轮官方 vector 回退的失败报告。
本轮 `acceptance/` 为首次修复通过的历史快照；增加临时实参与转移检查后重新
验收的当前版本在 `final-acceptance/`。索引不能重绑或使捕获的 slice 借用失效
等保守限制继续记录，其他开放特性不会被本轮专项通过清除。

发布工具在构建完成后冻结二进制摘要，每道后续门禁前后都核对；替换或移走编译器
会使验收失败。全量发布仍保留官方完整兼容门禁，不能用上述部分通过绕过它。
