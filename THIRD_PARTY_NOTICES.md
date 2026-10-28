# Third-party sources and notices

ModuleSafety is an independent experimental Clang extension. It is not an
official LLVM, Circle, Safe C++ or Rust release, and no endorsement by their
authors or organizations is implied. Names here identify reference projects.

## LLVM / Clang 22.1.2

- Upstream: https://github.com/llvm/llvm-project, release `llvmorg-22.1.2`.
- Distributed material: upstream context and modified code in
  `frontend/clang-22.1.2.patch`.
- License: Apache-2.0 WITH LLVM-exception, plus applicable legacy or individual
  upstream terms. The unmodified root license is in `LICENSES/LLVM.txt`; existing
  notices in patch context remain in place.
- The patch is a **modified version**, adding project safety syntax, type and
  region relationships, diagnostics, serialization and code generation. The
  modified-file inventory and resulting hashes are in `frontend/source-hashes.json`.
  Original project additions are covered by the compiler license in `LICENSING.md`;
  the upstream portions retain their existing terms.
- Full LLVM sources, SDKs and built libraries are not shipped in this source
  snapshot. Binary packages need their own inventory of the components actually
  included, corresponding source obligations and applicable notices.

The upstream license includes the University of Illinois/NCSA legacy notice and
explains how third-party exceptions are identified. Do not remove per-file
copyright or license headers when applying or repackaging the patch.

## Safe C++ / std2

- Upstream: https://github.com/cppalliance/safe-cpp.
- Fixed revision: `889685274438ca20344d4d9cb472e4392c4e35a9`.
- Origin: `libsafecxx/single-header/std2.h`.
- Distributed adaptation: `include/std2/std2.h`; preserves its upstream
  identification and is accompanied by `include/std2/LICENSE` (Boost Software
  License 1.0). A second verbatim license copy is in `LICENSES/BSL-1.0.txt`.
- Modifications adapt iterator concepts, associated traits and checked compiler
  integration. See `include/std2/README.md` and the implementation history.
- The small std2 excerpt discussed in `IMPLEMENTATION-STATUS.md` and adapter
  fragments exercised by `tests/std2_concepts.py` derive from this same reference;
  those upstream fragments retain the Boost license.
- Untouched official test sources are read from a locally fetched checkout;
  the checkout itself is not bundled with this source snapshot.

## Circle and mdspan: local references only

Circle reference: https://github.com/seanbaxter/circle,
revision `b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc`.
No general redistribution license was found in the inspected reference tree.
The project records feature names, paths, hashes and links for comparison;
it does not bundle that reference tree or grant rights to it. Reference access
does not imply redistribution permission. Similarity checks are a review aid,
not proof of independent authorship or complete legal clearance.

mdspan reference: https://github.com/seanbaxter/mdspan,
revision `774a1f0c401144d88fdf4d655a70b777b879f4b4`.
The locally inspected reference carries a BSD three-clause license with a Sandia
notice. That tree is not distributed here; if its code is later incorporated,
include its exact applicable copyright and license notices at that time.

## C++ working draft N4861: local audit input only

Origin: https://github.com/cplusplus/draft/tree/n4861.
`standards/n4861/manifest.json` records archive and source hashes used by the UB
inventory. The prepared source repository excludes `standards/n4861/source/`
and the downloaded archive. Project-generated inventories contain locations,
hashes and review metadata rather than a bundled standards text.

The development repository's old commits contain draft sources. **Do not push
that history as the prepared public repository.** Use the independent snapshot
described in `docs/PUBLISHING.md`. Exclusion is a publication-scope decision,
not a finding about all possible permissions to distribute the draft.

## Developer tools

LLVM, Lean, Z3, CMake, Ninja, Python, system libraries and SDKs are external build
or validation dependencies. Their installations and archives are not included
in this source snapshot. This notice does not cover a future binary distribution.
