#!/usr/bin/env python3
"""A `choice` owns one alternative: construction, `match`, `drp` and the
generated destructor, at -O0/-O2 under ASan/UBSan, with the refusals that go
with them.

Slice element access and the `__rel_read`/`__rel_write` intrinsics are not
covered here yet: their code generation is written but has no exercised
spelling in this suite, so a test would only restate the implementation.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / 'llvm-build/bin/clang'

MODULE = '''module;
#include <new>
export module choicemod;

// A payload that owns memory and counts its own destruction: a second
// destruction is both visible in the count and caught by ASan.
unsigned drops = 0u;
export unsigned count() { unsafe { return drops; } }

export struct Counted {
  unsigned value;
  unsigned* heap;

  explicit Counted(unsigned v) : value(v), heap(nullptr) {
    unsafe { heap = new unsigned(v); }
  }
  Counted(const Counted&) = delete;
  Counted(Counted&&) = delete;
  ~Counted() {
    unsafe {
      delete heap;
      heap = nullptr;
      ++drops;
    }
  }
};

export choice Box {
  default empty,
  counted(Counted);

  // Reading the payload by relocation moves it into the arm binding, so the
  // choice is left with no active alternative.
  unsigned value(self^) noexcept safe {
    return match(*self) -> unsigned {
      .counted(c) => c.value;
      .empty      => 0u;
    };
  }

  // A watch pattern inspects the tag alone: the payload stays where it is.
  // `drp` on a borrowed place ends the referent's lifetime in place: the tag
  // records the move so the owner's own destructor leaves the value alone.
  void forget(self^) noexcept safe { drp *self; }

  bool filled(self const^) noexcept safe {
    return match(*self) {
      .counted(_) => true;
      .empty      => false;
    };
  }

};

export Box wrap(unsigned v) safe { return .counted(Counted(v)); }
export Box blank() safe { return .empty; }

export unsigned run() safe {
  unsigned failures = 0u;
  {
    // The payload moves into the arm binding and is dropped there.
    Box b = wrap(7u);
    if ((mut b.value()) != 7u)
      failures |= 1u;
  }
  if (count() != 1u)
    failures |= 2u;
  {
    // An empty box drops nothing.
    Box e = blank();
    if (e.filled())
      failures |= 4u;
    if ((mut e.value()) != 0u)
      failures |= 8u;
  }
  if (count() != 1u)
    failures |= 16u;
  {
    // Never matched: the choice still owns the payload and drops it.
    Box w = wrap(5u);
    if (!w.filled())
      failures |= 32u;
  }
  if (count() != 2u)
    failures |= 64u;
  {
    // A watch leaves the payload owned; the choice drops it at scope exit.
    Box v = wrap(9u);
    if (!v.filled())
      failures |= 128u;
    if ((mut v.value()) != 9u)
      failures |= 256u;
  }
  if (count() != 3u)
    failures |= 512u;
  {
    // `drp` ends the lifetime here: the payload is destroyed at the drop, and
    // the scope exit must not destroy it a second time.
    Box d = wrap(11u);
    drp d;
    if (count() != 4u)
      failures |= 1024u;
  }
  if (count() != 4u)
    failures |= 2048u;
  {
    // The drop through the borrow destroys the payload once, in place, and the
    // owner's scope exit must not destroy it again.
    Box bd = wrap(13u);
    mut bd.forget();
    if (count() != 5u)
      failures |= 4096u;
  }
  if (count() != 5u)
    failures |= 8192u;
  unsigned before_owned_match = count();
  {
    Box owned = wrap(17u);
    unsigned taken = match(owned) -> unsigned {
      .counted(c) => c.value;
      .empty => 0u;
    };
    if (taken != 17u) failures |= 16384u;
  }
  if (count() != before_owned_match + 1u) failures |= 32768u;
  return failures;
}
'''

MAIN = 'import choicemod;\nint main() { return static_cast<int>(run()); }\n'

# Each refusal names the diagnostic the checker or the frontend must produce.
REFUSALS = [
    # A match must handle every alternative the choice can hold.
    ('unsigned f() safe { Box b = blank();'
     ' return match(b) -> unsigned { .counted(c) => c.value; }; }',
     'does not handle every alternative'),
    # A match may name an alternative once.
    ('unsigned f() safe { Box b = blank();'
     ' return match(b) -> unsigned { .empty => 0u; .empty => 1u; }; }',
     'repeats an arm'),
    # A catch-all arm cannot hide the arms that follow it.
    ('unsigned f() safe { Box b = blank();'
     ' return match(b) -> unsigned { _ => 0u; .empty => 1u; }; }',
     'catch-all match arm must come last'),
    # A binding needs an alternative that carries something to bind.
    ('unsigned f() safe { Box b = blank();'
     ' return match(b) -> unsigned { .empty(e) => 0u; .counted(c) => c.value; }; }',
     'requires an alternative with a payload'),
    # An alternative whose destructor is deleted cannot be owned by a choice.
    ('struct Dead { ~Dead() = delete; };\n'
     'export choice Bad { default none, dead(Dead); };\n',
     'deleted destructor'),
    # A dropped place has no value left to read.
    ('unsigned f() safe { Box b = wrap(2u); drp b;'
     ' return b.filled() ? 1u : 0u; }',
     'relocated'),
    # A method that relocates its receiver consumes it: the caller may not use
    # the receiver again.
    ('unsigned f() safe { Box b = wrap(3u); unsigned v = mut b.value();'
     ' return b.filled() ? v + 1u : v; }',
     'moved'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='choice-match-') as directory:
        tmp = pathlib.Path(directory)
        policy = tmp / 'policy.json'
        policy.write_text(json.dumps({'version': 1,
                                      'modules': {'choicemod': 'safe'}}))
        base = [str(clang), '--driver-mode=g++',
                '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
                '-std=c++20', '-fprebuilt-module-path=' + str(tmp)]
        checked = ['-fcircle-safety', '-fcircle-borrow-values',
                   '-fmodule-safety-policy=' + str(policy)]

        def compiles(args, ok=True, needle=''):
            result = subprocess.run(base + args, text=True, capture_output=True)
            assert (result.returncode == 0) == ok and needle in result.stderr, \
                result.stderr + '\n' + (source.read_text() if source.exists() else '')
            assert 'PLEASE submit' not in result.stderr and \
                'frontend command failed' not in result.stderr, result.stderr

        for optimization in ('-O0', '-O2'):
            sanitized = [optimization,
                         '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
            source = tmp / 'choicemod.cppm'
            source.write_text(MODULE)
            compiles(sanitized + checked + ['--precompile', str(source),
                                            '-o', str(tmp / 'choicemod.pcm')])
            # The module was checked when it was precompiled, exactly as the
            # library modules are: the object and link steps carry no checker.
            compiles(sanitized + ['-c', str(tmp / 'choicemod.pcm'),
                                  '-o', str(tmp / 'choicemod.o')])
            client = tmp / 'main.cpp'
            client.write_text(MAIN)
            binary = tmp / 'run'
            compiles(sanitized + [str(client), str(tmp / 'choicemod.o'),
                                  '-o', str(binary)])
            subprocess.run([str(binary)], check=True, timeout=30)

            for body, needle in REFUSALS:
                # The refusal is the module plus the offending declaration, so
                # it can name the choice the module exports.
                source.write_text(MODULE + '\n' + body)
                compiles(sanitized + checked + ['-fsyntax-only', str(source)],
                         False, needle)

    print('choice construction, match relocation, drp and the generated '
          'destructor pass at -O0/-O2 under ASan/UBSan, with 6 refusals per '
          'optimization level')


if __name__ == '__main__':
    main()
