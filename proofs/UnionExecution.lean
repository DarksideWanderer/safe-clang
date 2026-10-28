import Std
namespace ModuleSafety
variable {Field : Type} [DecidableEq Field]
inductive UnionOp (Field : Type) where
  | write (field : Field)
  | read (field : Field)
  | forget
inductive Result (Field : Type) where
  | normal (active : Option Field)
  | ub

def rep (abstract concrete : Option Field) : Prop := abstract = none ∨ abstract = concrete

def check (op : UnionOp Field) (state : Option Field) : Option (Option Field) :=
  match op with
  | .write f => some (some f)
  | .read f => if state = some f then some state else none
  | .forget => some none

def execute (op : UnionOp Field) (state chosen : Option Field) : Result Field :=
  match op with
  | .write f => .normal (some f)
  | .read f => if state = some f then .normal state else .ub
  | .forget => .normal chosen

theorem checked_step {op : UnionOp Field} {abstract abstractNext concrete chosen : Option Field}
    (represented : rep abstract concrete) (accepted : check op abstract = some abstractNext) :
    ∃ concreteNext, execute op concrete chosen = .normal concreteNext ∧ rep abstractNext concreteNext := by
  cases op with
  | write f =>
      simp [check] at accepted
      subst abstractNext
      exact ⟨some f, rfl, Or.inr rfl⟩
  | forget =>
      simp [check] at accepted
      subst abstractNext
      exact ⟨chosen, rfl, Or.inl rfl⟩
  | read f =>
      by_cases active : abstract = some f
      · simp [check, active] at accepted
        have concreteActive : concrete = some f := by
          rcases represented with unknown | same
          · rw [unknown] at active
            cases active
          · exact same.symm.trans active
        refine ⟨concrete, ?_, ?_⟩
        · simp [execute, concreteActive]
        · exact Or.inr (accepted.symm.trans concreteActive.symm)
      · simp [check, active] at accepted

def checkProgram : List (UnionOp Field) → Option Field → Option (Option Field)
  | [], state => some state
  | op :: rest, state => match check op state with
    | none => none
    | some next => checkProgram rest next

def executeProgram : List (UnionOp Field) → Option Field → List (Option Field) → Result Field
  | [], state, _ => .normal state
  | op :: rest, state, choices =>
    let chosen := choices.headD none
    match execute op state chosen with
    | .ub => .ub
    | .normal next => executeProgram rest next choices.tail

theorem checked_program {ops : List (UnionOp Field)} {a final c : Option Field}
    (represented : rep a c) (accepted : checkProgram ops a = some final)
    (choices : List (Option Field)) :
    ∃ concreteFinal, executeProgram ops c choices = .normal concreteFinal ∧ rep final concreteFinal := by
  induction ops generalizing a c choices with
  | nil =>
      simp [checkProgram] at accepted
      subst final
      exact ⟨c, rfl, represented⟩
  | cons op rest ih =>
      cases step : check op a with
      | none => simp [checkProgram, step] at accepted
      | some next =>
          have remainder : checkProgram rest next = some final := by simpa [checkProgram, step] using accepted
          obtain ⟨concreteNext, execution, refinement⟩ := checked_step represented step (chosen := choices.headD none)
          obtain ⟨concreteFinal, tailExecution, tailRefinement⟩ := ih refinement remainder choices.tail
          refine ⟨concreteFinal, ?_, tailRefinement⟩
          change (match execute op c (choices.headD none) with
            | .ub => (Result.ub : Result Field)
            | .normal next => executeProgram rest next choices.tail) = Result.normal concreteFinal
          rw [execution]
          exact tailExecution
end ModuleSafety
#print axioms ModuleSafety.checked_step
#print axioms ModuleSafety.checked_program
