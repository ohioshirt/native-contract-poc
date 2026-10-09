---------------- MODULE AsyncSession ----------------
EXTENDS FiniteSets, Naturals, Sequences, AsyncContractData

VARIABLES state, pending, previousState, previousPending, event, responseClass, effects, rejection
vars == <<state, pending, previousState, previousPending, event, responseClass, effects, rejection>>
NoRejection == "__none__"
ResponseClasses == {"CURRENT", "STALE", "NA"}

Init ==
  /\ state = InitialState
  /\ pending = FALSE
  /\ previousState = InitialState
  /\ previousPending = FALSE
  /\ event = "__initial__"
  /\ responseClass = "NA"
  /\ effects = << >>
  /\ rejection = NoRejection

NextPending(row) ==
  IF row.pendingAction = "allocate" THEN TRUE
  ELSE IF row.pendingAction = "clear" THEN FALSE
  ELSE pending

Observe(newState, newPending, newEffects, newRejection, cls, name) ==
  /\ previousState' = state
  /\ previousPending' = pending
  /\ state' = newState
  /\ pending' = newPending
  /\ event' = name
  /\ responseClass' = cls
  /\ effects' = newEffects
  /\ rejection' = newRejection

Apply(row, cls) ==
  Observe(row.nextState, NextPending(row), row.effects, NoRejection, cls, row.event)

RejectAllocation(row) ==
  Observe(state, pending, << >>, ExhaustionRejection, "NA", row.event)

StaleResponse(row) ==
  Observe(state, pending, << >>, NoRejection, "STALE", row.event)

SimpleStep ==
  \E row \in AsyncRows:
    /\ row.state = state
    /\ row.event \in SimpleEvents
    /\ row.guard = "always"
    /\ (Apply(row, "NA") \/ (row.pendingAction = "allocate" /\ RejectAllocation(row)))

CurrentResponse(row) ==
  /\ row.state = state
  /\ row.event \in ResponseEvents
  /\ row.guard = "activeResponse"
  /\ state = "Refreshing"
  /\ pending
  /\ Apply(row, "CURRENT")

StaleResponseStep(row) ==
  /\ row.state = state
  /\ row.event \in ResponseEvents
  /\ row.guard = "activeResponse"
  /\ StaleResponse(row)

ResponseStep ==
  \E row \in AsyncRows:
    CurrentResponse(row) \/ StaleResponseStep(row)

Next == SimpleStep \/ ResponseStep
Spec == Init /\ [][Next]_vars

StateClosed == state \in States /\ previousState \in States
PendingExactlyRefreshing == pending = (state = "Refreshing")
EventClosed == event = "__initial__" \/ event \in Events
ResponseClassClosed == responseClass \in ResponseClasses
EffectsClosed == effects \in Seq(Effects) /\ Len(effects) <= MaxEffects
CurrentRequiresPending == responseClass = "CURRENT" => previousPending /\ previousState = "Refreshing"
StaleResponseSafety ==
  responseClass = "STALE" =>
    /\ state = previousState
    /\ pending = previousPending
    /\ effects = << >>
    /\ rejection = NoRejection
RejectedAtomic ==
  rejection = ExhaustionRejection =>
    /\ state = previousState
    /\ pending = previousPending
    /\ effects = << >>
RowTransitionSound ==
  event = "__initial__" \/ rejection = ExhaustionRejection \/ responseClass = "STALE" \/
  \E row \in AsyncRows:
    /\ row.state = previousState
    /\ row.event = event
    /\ row.nextState = state
    /\ row.effects = effects
    /\ pending = IF row.pendingAction = "allocate" THEN TRUE
                 ELSE IF row.pendingAction = "clear" THEN FALSE
                 ELSE previousPending

==============================
