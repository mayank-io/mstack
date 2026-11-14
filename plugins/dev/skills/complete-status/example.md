# Complete Status: worked example

An invented project ("Ledger import rewrite") owned by one session that also tracks landings. The first block is the full report, sent when MK asks "status?". The second is the event reply sent when a chain finishes. All names, ids, paths and SHAs are made up.

## 1. Full report (MK asked "status?")

**Ledger import rewrite: milestones 1 and 2 landed, milestone 3 is 3 of 5 tasks done, one item waits on you.**

### Project milestones

- ✅ Milestone 1, parse bank CSV exports into the common row format: landed 2026-11-02.
- ✅ Milestone 2, match imported rows against existing ledger entries: landed 2026-11-09.
- Milestone 3, reconcile mismatches and write corrections (in progress):

| Item | Owner | State | Notes |
|---|---|---|---|
| Detect amount mismatches between bank and ledger (T31) | import-dev | ✅ landed in chain 14 | |
| Detect date drift of up to three days (T32) | import-dev | ✅ landed in chain 15 | |
| Write correction entries for confirmed mismatches (T33) | import-dev | 🔄 in chain 16, step 3 of 5 (full test suite) | |
| Report unresolved mismatches as a CSV (T34) | import-dev | ⏳ queued behind chain 16 | land ready since 09:10 PST |
| Decide the rounding rule for foreign-currency rows (T35) | MK | ⛔ waiting on your review | `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

- ⏳ Milestone 4, schedule nightly imports with failure alerts: waits on milestone 3.
- ⏳ Milestone 5, retire the old import script: waits on milestone 4 running for one week.

### Backlog

**Done**

| Item | State |
|---|---|
| Reject CSV files with a missing header row (B12) | ✅ landed in chain 13 |
| Document the common row format (B14) | ✅ landed directly (docs only) |

**In flight**

| Item | Owning session | Stage | State |
|---|---|---|---|
| Write correction entries for confirmed mismatches (T33) | import-dev | in chain | 🔄 chain 16, step 3 of 5 |
| Speed up matching for ledgers over 100k rows (B17) | import-perf | plan review round 2 of 3 | 🔄 round 2 running, round 1 returned 4 findings, all fixed |
| Report unresolved mismatches as a CSV (T34) | import-dev | land ready | ⏳ queued behind chain 16 |

**Next**

| Item | State |
|---|---|
| Accept the second bank's export format (B18) | ⏳ starts when T34 lands |
| Add a dry-run flag to the import command (B19) | ⏳ after B18 |

### Landings

**Reached main, in time order**

| What | Start (PST) | End (PST) | Duration | Result | Pushed SHAs |
|---|---|---|---|---|---|
| Chain 13: reject CSV files with a missing header row (B12) | 11-12 14:02 | 14:36 | 34 min | ✅ landed | ledger `a41c9e2` |
| Direct docs landing: document the common row format (B14) | 11-12 15:10 | 15:11 | 1 min | ✅ landed | ledger-docs `7be0d15` |
| Chain 14: detect amount mismatches (T31) | 11-12 16:20 | 16:57 | 37 min | ✅ landed | ledger `c03f7aa` |
| Chain 15, first run: detect date drift (T32) | 11-13 07:05 | 07:31 | 26 min | ❌ failed at step 3, two matcher tests | none |
| Chain 15, second run: detect date drift (T32) | 11-13 07:58 | 08:33 | 35 min | ✅ landed | ledger `e9d2b40`, ledger-docs `1f6a3c8` |

**Chain in flight**

| Chain | Start (PST) | Running for | Current step |
|---|---|---|---|
| Chain 16: write correction entries for confirmed mismatches (T33) | 11-13 09:14 | 21 min | 🔄 step 3 of 5, full test suite |

**Queue**

| # | Item | State |
|---|---|---|
| 1 | Report unresolved mismatches as a CSV (T34) | ⏳ land ready, starts when chain 16 ends |

**Not ready yet**

| Item | Why not |
|---|---|
| Speed up matching for ledgers over 100k rows (B17) | 🔄 plan review round 2 of 3 still running, no code yet |
| Decide the rounding rule for foreign-currency rows (T35) | ⛔ design waits on your review: `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

**Mains**

| Repo | main SHA |
|---|---|
| ledger | `e9d2b40` |
| ledger-docs | `1f6a3c8` |

### Decisions waiting on MK

| Decision | State | Open this |
|---|---|---|
| D7, whether foreign-currency rows round half-even or half-up | ⛔ waiting on you; both options costed in section 4 of the design | `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

### Blockers

| Blocker | State | Time remaining (est.) | Hinges on |
|---|---|---|---|
| Chain 16 must finish before T34 can land | 🔄 running | est. 15 min | chains have taken 34 to 37 min; 21 min elapsed |
| T34 chain | ⏳ queued | est. 35 min | one chain at observed pace, no failed run |
| B17 plan review | 🔄 round 2 of 3 | est. 50 min | two rounds left at about 25 min each; a round with findings adds a fix pass |
| D7 rounding rule | ⛔ waiting on you | est. 45 min after your answer | one implementation pass plus one chain |
| **Total to milestone 3 landed** | | **est. 1 h 35 min after your D7 answer** | chain 16 and T34 run meanwhile; B17 is not on this path |

### Paused on MK's word

⏸ Import from the brokerage API (B9), paused 2026-11-05 until milestone 5 is done. ⏸ Multi-currency ledger support (B11), paused 2026-11-08, no resume date.

Next project: nightly import scheduling with failure alerts (milestone 4).

## 2. Event reply (chain 16 finished, 20 minutes later)

**Chain 16 landed: correction entries for confirmed mismatches (T33) are on main at `5b7e1d3`; chain 17 started for the unresolved-mismatch CSV report (T34).**

### Project milestones

- ✅ Milestone 1, parse bank CSV exports into the common row format: landed 2026-11-02.
- ✅ Milestone 2, match imported rows against existing ledger entries: landed 2026-11-09.
- Milestone 3, reconcile mismatches and write corrections (in progress):

| Item | Owner | State | Notes |
|---|---|---|---|
| Detect amount mismatches between bank and ledger (T31) | import-dev | ✅ landed in chain 14 | |
| Detect date drift of up to three days (T32) | import-dev | ✅ landed in chain 15 | |
| Write correction entries for confirmed mismatches (T33) | import-dev | ✅ landed in chain 16 | |
| Report unresolved mismatches as a CSV (T34) | import-dev | 🔄 in chain 17, step 1 of 5 | |
| Decide the rounding rule for foreign-currency rows (T35) | MK | ⛔ waiting on your review | `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

- ⏳ Milestone 4, schedule nightly imports with failure alerts: waits on milestone 3.
- ⏳ Milestone 5, retire the old import script: waits on milestone 4 running for one week.

### Backlog

**Done**

| Item | State |
|---|---|
| Reject CSV files with a missing header row (B12) | ✅ landed in chain 13 |
| Document the common row format (B14) | ✅ landed directly (docs only) |

**In flight**

| Item | Owning session | Stage | State |
|---|---|---|---|
| Report unresolved mismatches as a CSV (T34) | import-dev | in chain | 🔄 chain 17, step 1 of 5 |
| Speed up matching for ledgers over 100k rows (B17) | import-perf | plan review round 3 of 3 | 🔄 round 3 running, round 2 returned 1 finding, fixed |

**Next**

| Item | State |
|---|---|
| Accept the second bank's export format (B18) | ⏳ starts when T34 lands |
| Add a dry-run flag to the import command (B19) | ⏳ after B18 |

### Landings

**Reached main, in time order**

| What | Start (PST) | End (PST) | Duration | Result | Pushed SHAs |
|---|---|---|---|---|---|
| Chain 13: reject CSV files with a missing header row (B12) | 11-12 14:02 | 14:36 | 34 min | ✅ landed | ledger `a41c9e2` |
| Direct docs landing: document the common row format (B14) | 11-12 15:10 | 15:11 | 1 min | ✅ landed | ledger-docs `7be0d15` |
| Chain 14: detect amount mismatches (T31) | 11-12 16:20 | 16:57 | 37 min | ✅ landed | ledger `c03f7aa` |
| Chain 15, first run: detect date drift (T32) | 11-13 07:05 | 07:31 | 26 min | ❌ failed at step 3, two matcher tests | none |
| Chain 15, second run: detect date drift (T32) | 11-13 07:58 | 08:33 | 35 min | ✅ landed | ledger `e9d2b40`, ledger-docs `1f6a3c8` |
| Chain 16: write correction entries for confirmed mismatches (T33) | 11-13 09:14 | 09:50 | 36 min | ✅ landed | ledger `5b7e1d3` |

**Chain in flight**

| Chain | Start (PST) | Running for | Current step |
|---|---|---|---|
| Chain 17: report unresolved mismatches as a CSV (T34) | 11-13 09:52 | 3 min | 🔄 step 1 of 5, rebase onto main |

**Queue**

| # | Item | State |
|---|---|---|
| | none | |

**Not ready yet**

| Item | Why not |
|---|---|
| Speed up matching for ledgers over 100k rows (B17) | 🔄 plan review round 3 of 3 still running, no code yet |
| Decide the rounding rule for foreign-currency rows (T35) | ⛔ design waits on your review: `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

**Mains**

| Repo | main SHA |
|---|---|
| ledger | `5b7e1d3` |
| ledger-docs | `1f6a3c8` |

### Waiting on MK

| Decision | State | Open this |
|---|---|---|
| D7, whether foreign-currency rows round half-even or half-up | ⛔ waiting on you; both options costed in section 4 of the design | `/Users/mk/dev/ledger/docs/designs/2026-11-12-fx-rounding-design.md` |

Next project: nightly import scheduling with failure alerts (milestone 4).
