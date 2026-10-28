#!/usr/bin/env python3
"""`unsafe` declarations audit their object; generic accessors keep elision."""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = root/'llvm-build/bin/clang'
flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values',
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

POSITIVE = '''
template<class T>
struct Cell {
  T* unsafe p_;
  explicit Cell(T* unsafe p) safe : p_(p) {}
  T^ borrow(self^) noexcept safe { return ^*self->p_; }
};

template<class T>
struct Wrapper {
  T value;
  T^ get(self^) noexcept safe { return ^self->value; }
};

int main() safe {
  int words[2] = {11, 22};
  Cell<int> c(&words[0]);
  int^ first = mut c.borrow();
  *first = 13;
  Wrapper<int> w{5};
  int^ second = mut w.get();
  // A pointer to a borrow value may be compared through its pointer
  // representation without erasing the handle's lifetime.
  int^* p = &second;
  int^* q = p;
  return *first == 13 && *second == 5 && words[0] == 13 &&
         p == q ? 0 : 1;
}
'''

NEGATIVES = (
    ('struct Bad { int* p_; int^ borrow(self^) noexcept safe '
     '{ return ^*self->p_; } };', 'raw pointer dereference'),
    ('struct Bad { int* p_; void step(self^) noexcept safe '
     '{ ++self->p_; } };', 'pointer arithmetic'),
)

with tempfile.TemporaryDirectory(prefix='circle-unsafe-declarations-') as directory:
    d = pathlib.Path(directory)
    source = d/'positive.cpp'
    binary = d/'positive'
    source.write_text(POSITIVE)
    r = subprocess.run([str(clang)] + flags + [str(source), '-o', str(binary)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr + POSITIVE
    r = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr

    for body, diagnostic in NEGATIVES:
        source.write_text(body)
        r = subprocess.run([str(clang)] + flags + ['-fsyntax-only', str(source)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode != 0, body
        assert diagnostic in r.stderr, r.stderr

print('unsafe declarations audit their object while plain raw pointer fields '
      'still require unsafe, and explicit-self template accessors keep '
      'elided borrows')
