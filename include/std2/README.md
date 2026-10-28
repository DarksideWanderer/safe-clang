# std2 adaptation

`std2.h` is adapted from `cppalliance/safe-cpp` revision
`889685274438ca20344d4d9cb472e4392c4e35a9`, originally
`libsafecxx/single-header/std2.h`. The header and its project adaptations retain
the accompanying **Boost Software License 1.0** in `LICENSE`. The project's
compiler GPL does not replace this header's license.

The adaptation expresses `iterator` and `make_iter` as concepts with explicit
`iterator_traits` and `make_iter_traits` specializations. Original implementation
operations are placed in the traits; associated types retain their names.
Consuming iteration is named `into_iter`, and mutable iteration `iter_mut`.
Send/sync contracts default to false for unknown types and pointers. Concept
satisfaction does not itself authorize an unsafe call: adapter implementations
must pass the safe-function checker.

`tests/std2_concepts.py` checks the adapter's associated types and operations.
`tests/std2_consumers.py` compiles, links and runs consumers of this header,
including checked containers and borrowing behavior. Both are included in the
native regression gate. Earlier reports that the complete consumer could not
compile describe historical versions; later fixed snapshots passed this gate.

Untouched upstream examples are a separate validation input, acquired locally
with `python3 tools/fetch_references.py safe-cpp`; they are not copied into the
public source snapshot. Their results do not establish complete compatibility
of every std2 operation or all Circle library implementations.

The dated scope, remaining gaps and reproduction instructions are in
[`compatibility/README.md`](../../compatibility/README.md) and
[`docs/VALIDATION.md`](../../docs/VALIDATION.md). This header requires the patched
native frontend; an ordinary Clang AST plugin cannot implement its native
syntax and type representation by itself.
