# Safe range-add / range-sum segment tree

Run from the repository root:

```sh
python3 examples/segment-tree/verify.py
```

`main.cpp` uses no templates, raw pointers, unsafe blocks or substitute standard
library. All functions are explicitly safe. The tree owns fixed arrays, accepts
1–64 elements, starts at zero, and exposes half-open intervals `[first,last)`.
Invalid ranges return false. Empty ranges are valid. Values and increments use
unsigned long long (64 bits on the validated macOS arm64 target), with modular
arithmetic. This is not a signed-integer or arbitrary-capacity implementation.

`sum(first,last,^answer)` demonstrates a checked mutable borrow of its output.
No method returns or stores a borrow. Consequently this example does not require
non-static class-value return lifetimes, heap relocation or generic containers.
Native constant-array indexing receives compiler-generated bounds checks.

The executable first checks sums 20 and 8 for a small example, then compares
32,000 randomized updates/queries against a plain array for sizes 1–64. Success
is exit code zero. Verification runs O0/O2, plain and ASan/UBSan, with ASan stack
use-after-return detection enabled, and checks two borrow-conflict refusals.
`build/segment-tree/evidence.json` binds commands and source/compiler hashes.
These checks validate this example, not full Circle compatibility or freedom
from undefined behavior throughout the compiler.
