---------------- MODULE Session ----------------
EXTENDS FiniteSets, Naturals, Sequences, ContractData

VARIABLES state, previousState, event, effects
vars == <<state, previousState, event, effects>>

Init ==
  /\ state = InitialState
  /\ previousState = InitialState
  /\ event = "__initial__"
  /\ effects = << >>

Next == \E row \in Transitions:
  /\ row[1] = state
  /\ previousState' = state
  /\ event' = row[2]
  /\ state' = row[3]
  /\ effects' = row[4]

Spec == Init /\ [][Next]_vars

StateClosed == state \in States
PreviousStateClosed == previousState \in States
EventClosed == event = "__initial__" \/ event \in Events
EffectsClosed == effects \in Seq(Effects) /\ Len(effects) <= MaxEffects
TransitionSound ==
  (event = "__initial__"
    /\ state = InitialState
    /\ previousState = InitialState
    /\ effects = << >>)
  \/ (event # "__initial__" /\
    \E row \in Transitions:
      /\ row[2] = event
      /\ row[3] = state
      /\ row[1] = previousState
      /\ row[4] = effects)

==============================
