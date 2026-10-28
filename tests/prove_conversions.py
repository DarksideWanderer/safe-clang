#!/usr/bin/env python3
"""SMT proofs of the numeric range model; not a proof of Clang or C++ codegen."""
import pathlib, shutil, subprocess, sys
solver = sys.argv[1] if len(sys.argv) > 1 else shutil.which('z3')
if not solver:
    raise SystemExit('Z3 is required; no proof was performed')
queries = []
def check(label, declarations, bad):
    queries.append((label, '(push)\n'+declarations+'\n(assert '+bad+')\n(check-sat)\n(pop)'))
widths = (2, 7, 8, 16, 17, 32, 63, 64, 127, 128)
types = [(1, False)] + [(width, signed) for width in widths for signed in (False, True)]
for sw, ss in types:
    sd = sw-int(ss); slo = -(1 << sd) if ss else 0; shi = (1 << sd)-1
    for tw, ts in types:
        td = tw-int(ts); tlo = -(1 << td) if ts else 0; thi = (1 << td)-1
        lossless = (not ss or ts) and td >= sd
        # Prove the implementation's width/sign predicate iff the entire
        # mathematical source range is contained in the target range.
        check(f'lossless {sw}/{ss} -> {tw}/{ts}', '',
              f'(not (= {str(lossless).lower()} (and (<= {tlo} {slo}) (<= {shi} {thi}))))')
        # Model the builtin's infinite-precision sum with zero and guarded
        # destination-width representation. Prove successful bits decode to
        # the original mathematical integer (no truncation/sign change).
        residue = f'(mod x {1<<tw})'
        decoded = f'(ite (>= {residue} {1<<(tw-1)}) (- {residue} {1<<tw}) {residue})' if ts else residue
        check(f'checked integer {sw}/{ss} -> {tw}/{ts}', '(declare-const x Int)',
              f'(and (<= {slo} x) (<= x {shi}) (<= {tlo} x) (<= x {thi}) (not (= x {decoded})))')
for width, signed in types:
    digits = width-int(signed); lower = -(1<<digits) if signed else 0; upper=1<<digits
    # For finite integral reals the runtime's exclusive power-of-two bound
    # exactly characterizes representability, avoiding rounded INT_MAX.
    check(f'float integer bounds {width}/{signed}', '(declare-const x Real)',
          f'(and (= x (to_real (to_int x))) (not (= (and (>= x {lower}) (< x {upper})) (and (>= x {lower}) (<= x {upper-1})))))')
for width in (1,)+widths:
    for count in range(width):
        scale = 1 << count
        product = f'(* x {scale})'
        # Within the actual value width, the checked left-shift round trip
        # succeeds exactly when multiplication loses no high bits. Storage
        # padding is intentionally absent from this model.
        restored = f'(div (mod {product} {1<<width}) {scale})'
        check(f'checked shift {width}/{count}', '(declare-const x Int)',
              f'(and (<= 0 x) (< x {1<<width}) (not (= (= {restored} x) (< {product} {1<<width}))))')
program='(set-logic ALL)\n'+'\n'.join(q for _,q in queries)+'\n'
result=subprocess.run([solver,'-in'],input=program,text=True,capture_output=True,timeout=60)
answers=result.stdout.splitlines()
if result.returncode or len(answers)!=len(queries) or any(a!='unsat' for a in answers):
    print(result.stdout, result.stderr)
    for (label,_), answer in zip(queries,answers):
        if answer!='unsat': print(label,answer)
    raise SystemExit('Range model proof failed')
print(f'Z3: {len(queries)} range-model obligations proved (all counterexample queries UNSAT)')
