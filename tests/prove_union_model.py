#!/usr/bin/env python3
"""Prove five local scalar-union activity lattice obligations with Z3."""
import pathlib,shutil,subprocess,sys
root=pathlib.Path(__file__).resolve().parent.parent
solver=sys.argv[1]if len(sys.argv)>1 else shutil.which('z3')
if not solver:raise SystemExit('Z3 is required; union model proof not completed')
r=subprocess.run([solver,str(root/'proofs/union_activity.smt2')],text=True,capture_output=True,timeout=60)
answers=r.stdout.split()
if r.returncode or answers!=['unsat']*5:raise SystemExit(r.stdout+r.stderr+'Union model obligations failed')
print('5 scalar union activity model obligations UNSAT; AST/CFG refinement remains unproved')
