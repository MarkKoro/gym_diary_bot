# Free-session source activity witness

H08 D1 native source contract. This writer is one part of the coordinated H08
release; it does not itself implement Core clock readers, admission, owner-reset
fences or certify full-H08 rollout/fallback.

`progressor_free_sessions` retains its existing six columns and order so that
old positional inserts remain compatible. New source knowledge is separate:

```sql
CREATE TABLE IF NOT EXISTS progressor_free_activity_proof(
 session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
 last_activity REAL NOT NULL,
 source_local_date TEXT NOT NULL,
 activity_timezone TEXT NOT NULL,
 proof_version INTEGER NOT NULL CHECK(proof_version=1),
 clock_kind TEXT NOT NULL CHECK(clock_kind='native_touch')
);
```

Only a successful existing current-day `progressor_free_workout.touch` writes
this witness, using the exact same source float clock, native session date and
`progressor_timezone_history.zone(users.tz or 'UTC')` used by its calendar comparison. The current native
writer transaction owns state and proof together. This attests an application
write, not physical exercise time, measured duration or an operation identifier.
Equal source clocks are possible; normal set-add operation receipts remain the
authority for individual append/replay identity.

`AFTER UPDATE OF last_activity` deletes the old proof even when the scalar is
unchanged. State INSERT/REPLACE and DELETE also invalidate stale proof. A current
validated touch writes state first and its replacement witness next, in that
same connection/transaction. There is no commit, nested BEGIN or executescript
inside `touch`/schema setup. An old compatible writer can save normal activity
but cannot leave a stale new-code witness attached to its changed/equal clock.

Explicit and90-minute finish never insert a proof or assign `last_activity`
in their conflict-update clause. A genuine witness and source UTC survive later
timezone changes; the finish-operation clock remains separate. A no-state
finish can save a timestamp while still lacking native_touch provenance. Neither
finish, migration, reads nor a timezone ledger can manufacture that provenance.
The Core reader must treat such rows as recorded_only rather than timed activity.

Schema setup creates zero proof rows. Install/reinstall the session-delete
trigger after the legacy sessions rebuild: dropping its table drops an attached
trigger. Ordinary session deletion clears proof without relying on enabled
foreign keys. Current owner wipe explicitly deletes proofs joined through that
owner's sessions before deleting them; the trigger also protects old-code wipe.
Existing broader wipe semantics, including intentional owned paid/receipt
cleanup, are unchanged.

No new touch is attached to a read, template, duration edit or other action
without an existing touch. Programmed sessions stay on their existing path.
Running drafts are not activity; their existing actual done/edit path owns touch.
Both native exercise surfaces still use their normal session and set writers.
Exact add_once replay returns before touch and cannot reopen a finished session
or renew proof. Idle completion remains5400seconds with the existing100-row
batch and unknown duration; waiting is never treated as exercise duration.

Retain the sidecar and invalidation triggers during code rollback, preserving
all later user writes. Never add columns to the old state table for this proof,
backfill witnesses from present timezone/labels, drop durable Core notification
policy objects or restore live databases to make an older reader appear safe.
The coordinated Core strict reader must validate exact session/day/clock pairing,
finite source UTC, valid source zone, native_touch/version1 and completed ISO.
Its adoption/admission and owner-reset gates remain independently required.

Focused synthetic checks live in `tests/test_free_activity_proof.py`. They cover
real native API/SQLite writers, rollback faults, both exercise surfaces, running
draft/done, exact add_once replay, equal old writes, migration, no-FK cleanup,
explicit and5400-second completion. Provider, delivery, physical Telegram and
full coordinated Core behavior are outside these native-only checks.


## Fixed-offset free activity — D1 V2, 28 October 2026

Free touch and current-session lookup use the existing native timezone-history
parser: valid IANA names or exact UTC±HH:MM, with maximum absolute14:00. The
source spelling is retained in the witness; its UTC clock/day are unchanged.
UTC+14:01, GMT+03:00 and plain +03:00 are not accepted aliases. GMT itself is a
valid IANA name and is not rejected. Invalid touch leaves existing native state
and witness unchanged; it never substitutes UTC. Both explicit and idle finish
still use saved UTC and never recertify against the current profile zone.

This deliberately fixes the free module's former IANA-only discrepancy with
the existing db.set_user_timezone grammar. The bot timezone selector currently
offers IANA names, while the shared explicit progressor_timezone.change CAS
additionally validates ZoneInfo and remains IANA-only. This scope does not widen
those independent chooser/CAS paths or rewrite stored timezone history.

Four new methods cover positive UTC+14:00/UTC-03:30 touch/local dates/current
reads, invalid-alias no-partial-activity behavior, and actual native setter/API
receipt replay. They add to the prior18 methods,22 total, before this candidate's
focused execution. Subcases are observations within methods, not extra cases.
Full native/Core and rollback acceptance remains a separate coordinated gate.
