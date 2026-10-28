import Std

/- Local semantic models. Connecting these models to Clang AST/CFG and
   proving the unsafe libraries are separate obligations. -/
namespace ModuleSafety

section Union
variable {Field : Type}

def Represents (abstract concrete : Option Field) : Prop :=
  abstract = none ∨ abstract = concrete

def joinActivity [DecidableEq Field] (left right : Option Field) : Option Field :=
  if left = right then left else none

theorem activity_read_sound {abstract concrete : Option Field} {field : Field}
    (represented : Represents abstract concrete) (accepted : abstract = some field) :
    concrete = some field := by
  rcases represented with unknown | known
  · simp [unknown] at accepted
  · rw [← known, accepted]

theorem activity_join_sound [DecidableEq Field] {left right concreteLeft concreteRight : Option Field}
    (hl : Represents left concreteLeft) (hr : Represents right concreteRight) :
    Represents (joinActivity left right) concreteLeft ∧
    Represents (joinActivity left right) concreteRight := by
  by_cases same : left = right
  · subst right
    simpa [joinActivity] using And.intro hl hr
  · simp [joinActivity, same, Represents]

theorem activity_forget_sound (concrete : Option Field) : Represents none concrete :=
  Or.inl rfl

theorem activity_write_sound (field : Field) : Represents (some field) (some field) :=
  Or.inr rfl
end Union

structure BorrowState (Var : Type) where
  ready : Var → Prop
  moved : Var → Prop
  origins : Var → Var → Prop

def joinBorrow {Var : Type} (a b : BorrowState Var) : BorrowState Var where
  ready v := a.ready v ∧ b.ready v
  moved v := a.moved v ∨ b.moved v
  origins v root := a.origins v root ∨ b.origins v root

def CanRead {Var : Type} (s : BorrowState Var) (v : Var) : Prop :=
  s.ready v ∧ ¬s.moved v ∧
  ∀ root, s.origins v root → s.ready root ∧ ¬s.moved root

def consumeState {Var : Type} (s : BorrowState Var) (receiver : Var) : BorrowState Var where
  ready := s.ready
  moved v := s.moved v ∨ v = receiver
  origins := s.origins

theorem consumed_receiver_unreadable {Var : Type} {s : BorrowState Var} {v : Var} :
    ¬ CanRead (consumeState s v) v := by
  intro checked
  exact checked.2.1 (Or.inr rfl)

theorem consumed_branch_unreadable {Var : Type} {a b : BorrowState Var} {v : Var} :
    ¬ CanRead (joinBorrow (consumeState a v) b) v := by
  intro checked
  exact checked.2.1 (Or.inl (Or.inr rfl))

structure AccessOrigins (Var : Type) where
  roots : Var → Prop
  parents : Var → Prop

structure LoanCapabilities (Var : Type) where
  roots : Var → Prop
  exclusive : Prop

def joinAccess {Var : Type} (a b : AccessOrigins Var) : AccessOrigins Var where
  roots root := a.roots root ∨ b.roots root
  parents alias := a.parents alias ∧ b.parents alias

def joinCapabilities {Var : Type} (a b : Var → LoanCapabilities Var) :
    Var → LoanCapabilities Var := fun alias => {
  roots := fun root => (a alias).roots root ∨ (b alias).roots root
  exclusive := (a alias).exclusive ∨ (b alias).exclusive }

def CompatibleAccess {Var : Type} (actor : AccessOrigins Var)
    (loans : Var → LoanCapabilities Var) (write : Prop) : Prop :=
  ∀ alias, ¬actor.parents alias → ∀ root,
    actor.roots root → (loans alias).roots root → ¬write ∧ ¬(loans alias).exclusive

theorem joined_access_left {Var : Type} {a b : AccessOrigins Var}
    {loansA loansB : Var → LoanCapabilities Var} {write : Prop}
    (checked : CompatibleAccess (joinAccess a b) (joinCapabilities loansA loansB) write) :
    CompatibleAccess a loansA write := by
  intro alias unrelated root actorOrigin loanOrigin
  have valid := checked alias (fun parent => unrelated parent.1) root
    (Or.inl actorOrigin) (Or.inl loanOrigin)
  exact ⟨valid.1, fun exclusive => valid.2 (Or.inl exclusive)⟩

theorem joined_access_right {Var : Type} {a b : AccessOrigins Var}
    {loansA loansB : Var → LoanCapabilities Var} {write : Prop}
    (checked : CompatibleAccess (joinAccess a b) (joinCapabilities loansA loansB) write) :
    CompatibleAccess b loansB write := by
  intro alias unrelated root actorOrigin loanOrigin
  have valid := checked alias (fun parent => unrelated parent.2) root
    (Or.inr actorOrigin) (Or.inr loanOrigin)
  exact ⟨valid.1, fun exclusive => valid.2 (Or.inr exclusive)⟩

theorem joined_read_left {Var : Type} {a b : BorrowState Var} {v : Var}
    (checked : CanRead (joinBorrow a b) v) : CanRead a v := by
  rcases checked with ⟨ready, unmoved, owners⟩
  refine ⟨ready.1, fun moved => unmoved (Or.inl moved), ?_⟩
  intro root origin
  have valid := owners root (Or.inl origin)
  exact ⟨valid.1.1, fun moved => valid.2 (Or.inl moved)⟩

theorem joined_read_right {Var : Type} {a b : BorrowState Var} {v : Var}
    (checked : CanRead (joinBorrow a b) v) : CanRead b v := by
  rcases checked with ⟨ready, unmoved, owners⟩
  refine ⟨ready.2, fun moved => unmoved (Or.inr moved), ?_⟩
  intro root origin
  have valid := owners root (Or.inr origin)
  exact ⟨valid.1.2, fun moved => valid.2 (Or.inr moved)⟩

def WholeRecovery (whole borrowing : Bool) : Prop :=
  whole = true ∧ borrowing = false

def assignState {Var : Type} (s : BorrowState Var) (target : Var)
    (whole borrowing : Bool) : BorrowState Var where
  ready v := s.ready v ∨ (WholeRecovery whole borrowing ∧ v = target)
  moved v := s.moved v ∧ ¬(WholeRecovery whole borrowing ∧ v = target)
  origins := s.origins

theorem partial_assignment_preserves_moved {Var : Type} {s : BorrowState Var}
    {target v : Var} (borrowing : Bool) (moved : s.moved v) :
    (assignState s target false borrowing).moved v := by
  refine ⟨moved, ?_⟩
  intro recovery
  have impossible : false = true := recovery.1.1
  cases impossible

theorem borrowed_assignment_preserves_moved {Var : Type} {s : BorrowState Var}
    {target v : Var} (whole : Bool) (moved : s.moved v) :
    (assignState s target whole true).moved v := by
  refine ⟨moved, ?_⟩
  intro recovery
  have impossible : true = false := recovery.1.2
  cases impossible

structure Memory (Var : Type) where
  alive : Var → Prop
  initialized : Var → Prop

def ReadyRefines {Var : Type} (state : BorrowState Var) (memory : Memory Var) : Prop :=
  ∀ v, state.ready v → memory.alive v ∧ memory.initialized v

theorem accepted_read_live {Var : Type} {s : BorrowState Var} {m : Memory Var} {v : Var}
    (refinement : ReadyRefines s m) (checked : CanRead s v) :
    (m.alive v ∧ m.initialized v) ∧
    ∀ root, s.origins v root → m.alive root ∧ m.initialized root := by
  refine ⟨refinement v checked.1, ?_⟩
  intro root origin
  exact refinement root (checked.2.2 root origin).1

/- Destruction and exception unwind preserve external aliases' origins.
   Removing an owner from ready must not remove it from surviving aliases. -/
def retireState {Var : Type} (s : BorrowState Var) (dead : Var → Prop) : BorrowState Var where
  ready v := s.ready v ∧ ¬ dead v
  moved := s.moved
  origins := s.origins

def retireMemory {Var : Type} (m : Memory Var) (dead : Var → Prop) : Memory Var where
  alive v := m.alive v ∧ ¬ dead v
  initialized := m.initialized

theorem retirement_preserves_refinement {Var : Type} {s : BorrowState Var}
    {m : Memory Var} (dead : Var → Prop) (refinement : ReadyRefines s m) :
    ReadyRefines (retireState s dead) (retireMemory m dead) := by
  intro v ready
  have previous := refinement v ready.1
  exact ⟨⟨previous.1, ready.2⟩, previous.2⟩

theorem retired_owner_unreadable {Var : Type} {s : BorrowState Var}
    {dead : Var → Prop} {v : Var} (ended : dead v) :
    ¬ CanRead (retireState s dead) v := by
  intro checked
  exact checked.1.2 ended

theorem retired_borrow_unreadable {Var : Type} {s : BorrowState Var}
    {dead : Var → Prop} {alias owner : Var}
    (borrow : s.origins alias owner) (ended : dead owner) :
    ¬ CanRead (retireState s dead) alias := by
  intro checked
  exact (checked.2.2 owner borrow).1.2 ended

theorem retirement_preserves_external_read {Var : Type} {s : BorrowState Var}
    {dead : Var → Prop} {v : Var} (checked : CanRead s v)
    (outside : ¬ dead v) (ownersOutside : ∀ root, s.origins v root → ¬ dead root) :
    CanRead (retireState s dead) v := by
  refine ⟨⟨checked.1, outside⟩, checked.2.1, ?_⟩
  intro root origin
  have previous := checked.2.2 root origin
  exact ⟨⟨previous.1, ownersOutside root origin⟩, previous.2⟩

inductive FrameState where
  | suspended | running | completed | destroyed
  deriving DecidableEq

inductive FrameStep : FrameState → FrameState → Prop where
  | resume : FrameStep .suspended .running
  | yield : FrameStep .running .suspended
  | complete : FrameStep .running .completed
  | cancel : FrameStep .suspended .destroyed
  | drop : FrameStep .completed .destroyed

theorem destroyed_frame_no_step {next : FrameState} : ¬FrameStep .destroyed next := by
  intro transition
  cases transition

theorem running_frame_cannot_destroy : ¬FrameStep .running .destroyed := by
  intro transition
  cases transition

-- Regions are validity sets, rather than assumed lexical interval lengths.
abbrev Region := Nat → Prop

def Outlives (long short : Region) : Prop := ∀ point, short point → long point

structure SharedRef (Value : Type) (Valid : Value → Nat → Prop) (region : Region) where
  value : Value
  valid : ∀ point, region point → Valid value point

def SharedRef.shorten {Value : Type} {Valid : Value → Nat → Prop}
    {long short : Region} (outlives : Outlives long short)
    (reference : SharedRef Value Valid long) : SharedRef Value Valid short where
  value := reference.value
  valid point active := reference.valid point (outlives point active)

theorem shortened_reference_valid {Value : Type} {Valid : Value → Nat → Prop}
    {long short : Region} (relation : Outlives long short)
    (reference : SharedRef Value Valid long) (point : Nat) (active : short point) :
    Valid (reference.shorten relation).value point :=
  reference.valid point (relation point active)

-- Universal region quantification is independent at each call site.
abbrev RankedRefFn (Value : Type) (Valid : Value → Nat → Prop) :=
  ∀ region : Region, SharedRef Value Valid region → SharedRef Value Valid region

theorem ranked_result_valid {Value : Type} {Valid : Value → Nat → Prop}
    (callback : RankedRefFn Value Valid) (region : Region)
    (input : SharedRef Value Valid region) (point : Nat) (active : region point) :
    Valid (callback region input).value point := (callback region input).valid point active

-- A generic associated family may depend on the region. The obligation is
-- explicit, so arbitrary associated types cannot assert validity for free.
structure LendingFamily (Owner Value : Type)
    (OwnerValid : Owner → Nat → Prop) (ValueValid : Value → Nat → Prop) where
  Item : Region → Type
  lend : ∀ region, SharedRef Owner OwnerValid region → Item region
  project : ∀ region, Item region → SharedRef Value ValueValid region

theorem associated_result_valid {Owner Value : Type}
    {OwnerValid : Owner → Nat → Prop} {ValueValid : Value → Nat → Prop}
    (family : LendingFamily Owner Value OwnerValid ValueValid) (region : Region)
    (owner : SharedRef Owner OwnerValid region) (point : Nat) (active : region point) :
    ValueValid (family.project region (family.lend region owner)).value point :=
  (family.project region (family.lend region owner)).valid point active

/- A reference to a borrow-carrying object needs both the object's storage
   and its fields' targets. This model is separate from the Clang extraction. -/
structure ReferenceOrigins (Var : Type) where
  knownStorage : Prop
  fields : Var → Prop
  storage : Var → Prop

def joinReference {Var : Type} (a b : ReferenceOrigins Var) : ReferenceOrigins Var where
  knownStorage := a.knownStorage ∧ b.knownStorage
  fields v := a.fields v ∨ b.fields v
  storage v := a.storage v ∨ b.storage v

def ReturnAllowed {Var : Type} (origins : ReferenceOrigins Var) (allowed : Var → Prop) : Prop :=
  origins.knownStorage ∧ ∀ v, origins.fields v ∨ origins.storage v → allowed v

theorem reference_join_left {Var : Type} {a b : ReferenceOrigins Var} {allowed : Var → Prop}
    (checked : ReturnAllowed (joinReference a b) allowed) : ReturnAllowed a allowed := by
  refine ⟨checked.1.1, ?_⟩
  intro v origin
  cases origin with
  | inl field => exact checked.2 v (Or.inl (Or.inl field))
  | inr storage => exact checked.2 v (Or.inr (Or.inl storage))

theorem reference_join_right {Var : Type} {a b : ReferenceOrigins Var} {allowed : Var → Prop}
    (checked : ReturnAllowed (joinReference a b) allowed) : ReturnAllowed b allowed := by
  refine ⟨checked.1.2, ?_⟩
  intro v origin
  cases origin with
  | inl field => exact checked.2 v (Or.inl (Or.inr field))
  | inr storage => exact checked.2 v (Or.inr (Or.inr storage))

theorem local_storage_rejected {Var : Type} {origins : ReferenceOrigins Var}
    {allowed : Var → Prop} {localOwner : Var}
    (localStorage : origins.storage localOwner) (notAllowed : ¬ allowed localOwner) :
    ¬ ReturnAllowed origins allowed := by
  intro checked
  exact notAllowed (checked.2 localOwner (Or.inr localStorage))

theorem unknown_temporary_rejected {Var : Type} {origins : ReferenceOrigins Var}
    {allowed : Var → Prop} (unknown : ¬ origins.knownStorage) :
    ¬ ReturnAllowed origins allowed := by
  intro checked
  exact unknown checked.1

end ModuleSafety

#print axioms ModuleSafety.activity_read_sound
#print axioms ModuleSafety.activity_join_sound
#print axioms ModuleSafety.activity_forget_sound
#print axioms ModuleSafety.activity_write_sound
#print axioms ModuleSafety.joined_read_left
#print axioms ModuleSafety.joined_read_right
#print axioms ModuleSafety.consumed_receiver_unreadable
#print axioms ModuleSafety.consumed_branch_unreadable
#print axioms ModuleSafety.joined_access_left
#print axioms ModuleSafety.joined_access_right
#print axioms ModuleSafety.partial_assignment_preserves_moved
#print axioms ModuleSafety.borrowed_assignment_preserves_moved
#print axioms ModuleSafety.accepted_read_live
#print axioms ModuleSafety.retirement_preserves_refinement
#print axioms ModuleSafety.retired_owner_unreadable
#print axioms ModuleSafety.retired_borrow_unreadable
#print axioms ModuleSafety.retirement_preserves_external_read
#print axioms ModuleSafety.destroyed_frame_no_step
#print axioms ModuleSafety.running_frame_cannot_destroy

#print axioms ModuleSafety.shortened_reference_valid
#print axioms ModuleSafety.ranked_result_valid
#print axioms ModuleSafety.associated_result_valid
#print axioms ModuleSafety.reference_join_left
#print axioms ModuleSafety.reference_join_right
#print axioms ModuleSafety.local_storage_rejected
#print axioms ModuleSafety.unknown_temporary_rejected
