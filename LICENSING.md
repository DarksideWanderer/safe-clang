# License scope

The project uses separate licenses for the compiler and the libraries used by
applications. These grants apply to original project contributions for which the
contributors hold the necessary rights. Existing third-party terms and notices
remain applicable; this document does not relicense third-party material.

| Paths | License for original project contributions |
| --- | --- |
| `src/`, `frontend/`, `tools/`, `tests/`, `proofs/`, build configuration, compatibility metadata and project documentation | **GPL-2.0-only** |
| `include/`, except third-party material in `include/std2/` | **Apache-2.0 WITH LLVM-exception** |
| `runtime/`, `examples/` | **Apache-2.0 WITH LLVM-exception** |
| `include/std2/std2.h` and project adaptations of that header | **BSL-1.0**; see `include/std2/LICENSE` |
| Third-party portions of `frontend/clang-22.1.2.patch` | Upstream LLVM terms; see `LICENSES/LLVM.txt` and `THIRD_PARTY_NOTICES.md` |

Original project material outside a specifically excepted path is licensed under
**GNU General Public License, version 2 only**, reproduced in `LICENSE`.
It is free software: you may redistribute it and/or modify it under that version
of the license. It is distributed without any warranty, including the implied
warranties of merchantability or fitness for a particular purpose. See `LICENSE`
for the full terms. This grant does not offer a later GPL version as an option.

Original project contributions to `include/`, `runtime/` and `examples/` are
licensed under the Apache License, Version 2.0, with LLVM Exceptions, reproduced
in those directories' `LICENSE` files and
`LICENSES/Apache-2.0-with-LLVM-exception.txt`. Those files may be used only in
compliance with that license and are provided on an "AS IS" basis without
warranties or conditions of any kind. The full license states the applicable
permissions and limitations.

Merely using the compiler does not place the application's own source under
the GPL. Code copied or linked into an application must be considered
separately. The library/header licenses above are intended to permit use in
applications under other licenses, subject to their terms. No universal claim
is made about every possible generated binary or external dependency.

LLVM's exception expressly addresses combinations of compiled LLVM software
with GPLv2 software. Retain the LLVM license and exception when distributing
such a combination; do not describe all upstream Clang code as newly relicensed
under GPLv2. Plain Apache-2.0 dependencies without that exception require a
separate compatibility check.

The locally acquired Circle references, C++ standards draft, toolchains and
downloaded repositories are **not licensed by this project** and are not included
in its prepared public source snapshot. Their presence on a developer's disk
does not authorize redistribution.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for pinned origins and
[docs/PUBLISHING.md](docs/PUBLISHING.md) for preparing a source publication.
