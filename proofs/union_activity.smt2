; Local abstract-domain proof for scalar union activity. 0 is unknown.
; Concrete activity 0 means no member is alive; positive IDs are member IDs.
; This does not prove AST/CFG extraction, alias resolution or LLVM lowering.
(set-logic QF_LIA)
(set-option :timeout 10000)
(define-fun represents ((abstract Int)(concrete Int)) Bool
  (and (>= abstract 0)(>= concrete 0)(or (= abstract 0)(= abstract concrete))))
(define-fun join ((a Int)(b Int)) Int (ite (= a b) a 0))
(define-fun accepts_read ((a Int)(member Int)) Bool (and (> member 0)(= a member)))
(declare-const a Int)(declare-const b Int)
(declare-const ca Int)(declare-const cb Int)(declare-const member Int)
; Join preserves both predecessor possibilities.
(push)
(assert (and (represents a ca)(represents b cb)
  (not (and (represents (join a b) ca)(represents (join a b) cb)))))
(check-sat)(pop)
; An accepted read accesses the concrete active member.
(push)
(assert (and (represents a ca)(accepts_read a member)(not (= ca member))))
(check-sat)(pop)
; A scalar assignment activates its member in both semantics.
(push)
(assert (and (> member 0)(not (represents member member))))
(check-sat)(pop)
; Unknown mutation loses knowledge and cannot license a read.
(push)
(assert (accepts_read 0 member))
(check-sat)(pop)
; Join is associative: fixed-point merge order cannot manufacture activity.
(push)
(assert (and (>= a 0)(>= b 0)(>= member 0)
 (not (= (join (join a b) member)(join a (join b member))))))
(check-sat)(pop)
