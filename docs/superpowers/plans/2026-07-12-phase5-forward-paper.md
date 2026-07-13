# Phase-5 Forward-Paper Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase-5 forward-paper pipeline locked in `docs/preregs/2026-07-12_phase5-forward-paper.md`: append-only per-family ledgers, PaperBroker stub, EOD signal job, open-fill job, hourly monitor, Discord alerts, and merge-only Google Drive sync.

**Architecture:** A new `src/sts/forward/` package reuses the exact backtested semantics — `sts.study.h4_candidates.candidates_for` for signals, `run_h4b_study.RANK_KEY` + throttle (4 per rolling 5 sessions) for H1 expression, `risk.position_size`/`risk.manage_bar` for sizing/exits — around an append-only JSONL journal that is the single source of truth. Jobs are thin scripts over the package; every job is idempotent (re-run for a processed date = no-op) and resume-capable. State lives in the journal, never in process memory.

**Tech Stack:** Python 3.14 (existing repo), pandas, yfinance (already used by `sts.data.fetch`), `urllib.request` for Discord webhook (no new deps), `rclone` (installed, remotes `gdrive:`/`bhat-trading-drive:` exist) for Drive sync.

## Global Constraints (verbatim from the locked prereg)

- Shared book: $100,000; 0.75% risk/trade on current shared equity; max 8 concurrent positions; 80% max deployed; 15% per-position notional cap; one position per symbol (cross-family blocking); 2-session pre-earnings entry embargo.
- H2 candidates fill first (internal order: Phase-4 convention `(signal_date, symbol)`); H1 then competes under the full 4b expression: rank key `(is_seed DESC, rsi2_at_trigger ASC, reclaim_wait_sessions ASC)`, throttle max 4 new H1 entries per rolling 5 sessions.
- H1-solo companion book: separate $100,000 virtual book, 4b H1 expression alone (rank key, throttle 4/5, 8 slots, 80% deployed, no H2 interaction, no cross-family blocking), `source: local-h1solo`.
- Two ledgers, one per family: `ledger/h1.jsonl`, `ledger/h2.jsonl`, append-only. Daily book snapshots in `ledger/equity.jsonl` (date, book, equity, cash, $ deployed, open_count). Row fields exactly as prereg §"Forward ledger (locked schema)". `entry_id = book:family:symbol:signal_date`. `tp1` = locked 2R ATR target (full-size exit); `tp2` = null (reserved).
- Costs: 5 bps/side + $1/order (stub fills at session open + this cost model).
- Exit taxonomy verbatim: `stop / stop_gap / target / time / censored` (these are exactly `risk.manage_bar`'s reasons).
- Skipped/blocked candidates (slot, throttle, embargo, dup-symbol) go to the signal journal with reasons — never silently dropped. Missed sessions must be recorded explicitly.
- Intraday monitor is advisory only — never a fill authority.
- Discord message format for entries (docs/PLAN.md §Phase 6): `{ticker} Entry @{price_low}-{price_high}, TP1: @{tp1}, TP2: @{tp2}, SL: {sl}. Config: {config_name}. Alerted at {timestamp PT}.` TP2 prints `-` while reserved.
- Drive: forward ledgers → folder id `1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5` (**merge-only, never overwrite remote content destructively — remote is source of truth, only merged into**). Backtest artifacts (`runs/`, `docs/preregs/`) → folder id `1i11V4ooDMRQbbVSkwzwbFr7lKlOoNcEQ` (one-way copy, no deletes). Sync runs daily after signal gen + ledger upkeep, in all deployments.
- No signal or expression parameter moves. No new detector logic. `DISCORD_WEB_HOOK` comes from `.env` via `sts.env.load()`.
- Long-running steps must be resumable and report time taken / ETA (user global rule).

## File Structure

```
src/sts/forward/
  __init__.py
  journal.py      # generic append-only JSONL with atomic append; the storage primitive
  ledger.py       # ledger schema, entry_id, row versioning, state materialization, merge
  alerts.py       # Discord webhook client (module named alerts to avoid discord.py clash)
  broker.py       # PaperBroker interface + StubPaperBroker (open fill + cost model)
  book.py         # BookState: equity/cash/open positions from ledger; charter checks; sizing
  pipeline.py     # EOD logic: upkeep (exits), signal gen (ranking/throttle/queue), snapshots
  sync.py         # rclone-based Drive sync: merge-only ledgers, one-way backtest copy
scripts/
  forward_eod.py      # nightly: fetch → upkeep → signals → alerts → sync
  forward_fill.py     # next open: fill queued entries via broker → ledger → alerts → sync
  forward_monitor.py  # hourly: quotes on open positions, advisory alerts
  forward_sync.py     # standalone sync entry point
deploy/
  launchd/            # com.sts.forward-{eod,fill,monitor}.plist + install.sh (local laptop)
ledger/               # created at runtime; .gitignore'd? NO — ledgers are committed? -> ledgers live on Drive; keep local copies in repo dir but git-ignored (Drive is source of truth)
tests/forward/        # test_journal.py test_ledger.py test_broker.py test_book.py test_pipeline.py test_sync.py test_alerts.py
```

`.gitignore` gains `ledger/` (Drive is the source of truth for forward ledgers; git holds code and preregs).

---

### Task 1: Journal primitive (`journal.py`)

**Files:** Create `src/sts/forward/__init__.py` (empty), `src/sts/forward/journal.py`, `tests/forward/test_journal.py`.

**Produces:** `class Journal(path: Path)` with `append(record: dict) -> None` (adds nothing to record; caller owns fields; JSON one-line, `sort_keys=True`, atomic append with `flush+fsync`), `read() -> list[dict]` (tolerates and skips a trailing partial line, logging a warning), `__len__`. Module fn `merge_lines(a: list[str], b: list[str], key_fn) -> list[str]`: union preserving first-seen order of `a` then new-from-`b`, dedupe by `key_fn(parsed_line)`; on key collision with differing content, keep the line whose parsed `updated_at` (fallback: raw string) is larger and log a warning. Pure, no I/O.

- [ ] **Step 1:** Write tests: append→read round-trip; append is one line per record; `read()` skips a manually truncated last line; `merge_lines` unions, dedupes exact duplicates, resolves collision by `updated_at`, is idempotent (`merge(merge(a,b),b) == merge(a,b)`).
- [ ] **Step 2:** Run `pytest tests/forward/test_journal.py -q` → FAIL (module missing).
- [ ] **Step 3:** Implement (~60 lines). Follow the atomic-write style of `sts/data/store.py`.
- [ ] **Step 4:** Tests pass. **Step 5:** Commit `feat(forward): append-only JSONL journal primitive`.

### Task 2: Ledger module (`ledger.py`)

**Files:** Create `src/sts/forward/ledger.py`, `tests/forward/test_ledger.py`. Modify `.gitignore` (+`ledger/`).

**Interfaces — Produces:**
```python
SCHEMA_VERSION = 1
BOOKS = ("shared", "h1solo")
SOURCES = {"shared": "local-shared", "h1solo": "local-h1solo"}

def entry_id(book: str, family: str, symbol: str, signal_date: dt.date) -> str  # "shared:h1:NVDA:2026-07-10"

@dataclass class LedgerPaths: root: Path = Path("ledger")   # .h1, .h2, .equity, .signals properties

class Ledger:  # wraps the two family journals + equity + signals
    def __init__(self, paths: LedgerPaths = LedgerPaths()): ...
    def append_row(self, row: dict) -> None      # validates required fields vs schema, stamps schema_version, seq (prev seq for entry_id + 1), updated_at (UTC iso); routes to h1/h2 journal by row["family"]
    def state(self) -> dict[str, dict]           # entry_id -> latest row (max seq) across both family journals
    def open_rows(self, book: str | None = None) -> list[dict]
    def held_symbols(self, book: str) -> set[str]
    def append_equity_snapshot(self, snap: dict) -> None   # no-op if (date, book) already present  → idempotent
    def equity_series(self, book: str) -> list[dict]
    def append_signal(self, rec: dict) -> None   # no-op if (signal_date, book, "entry_id") already present
    def signals(self, signal_date: dt.date | None = None) -> list[dict]
    def processed_upkeep_dates(self) -> set[dt.date]  # from signal journal control rows kind="upkeep_done"
```
Row required fields (prereg-locked): `entry_id, schema_version, family, source, ticker, signal_date, timestamp, qty, entry_ref, entry_fill, entry_price_range, stop_initial, sl, tp1, tp2, status, usd_deployed, exit_price, exit_timestamp, exit_reason, fees_total, pnl_usd, r_net` (+ bookkeeping `book, seq, updated_at`). Open rows carry `None` for exit fields; `tp2` always `None` this phase. Signal-journal records carry `kind` ∈ {`candidate`, `skip`, `missed_session`, `upkeep_done`} with `reason` for skips (`slot`, `throttle`, `embargo`, `dup_symbol`, `deploy_cap`, `size_zero`).

- [ ] **Step 1:** Tests: schema validation rejects a row missing `stop_initial`; `append_row` auto-increments `seq` per `entry_id`; `state()` returns latest version; open→closed transition; equity snapshot idempotency; signal idempotency; H1 rows land in `ledger/h1.jsonl` and H2 rows in `ledger/h2.jsonl` (tmp_path).
- [ ] **Step 2:** FAIL. **Step 3:** Implement on top of Task-1 `Journal`. **Step 4:** PASS. **Step 5:** Commit `feat(forward): per-family append-only ledger with locked schema`.

### Task 3: Discord alerts (`alerts.py`)

**Files:** Create `src/sts/forward/alerts.py`, `tests/forward/test_alerts.py`.

**Produces:**
```python
def send(text: str, webhook: str | None = None) -> bool
    # webhook default: os.environ["DISCORD_WEB_HOOK"] (sts.env.load() already called by scripts).
    # urllib POST json {"content": text[:1900]}; 3 tries, 2s/4s backoff; returns False (and logs) on
    # failure or missing webhook — alert failure NEVER crashes a job.
def entry_alert(cand: dict) -> str
    # "{ticker} Entry @{low}-{high}, TP1: @{tp1}, TP2: @-, SL: {sl}. Config: {config_name}. Alerted at {YYYY-MM-DD HH:MM AM/PM PT}."
def book_status(snapshots: list[dict]) -> str      # one line per book: equity, cash, deployed, open_count
def exit_alert(row: dict) -> str                    # "{ticker} EXIT {exit_reason} @{exit_price}, R={r_net:+.2f} ({book})"
```
Prices formatted `f"{x:.2f}"`. Timestamps via `zoneinfo.ZoneInfo("America/Los_Angeles")`.

- [ ] Tests: format functions exact-match golden strings; `send` posts payload to a monkeypatched `urllib.request.urlopen`, retries then returns False; missing webhook → False without raising. Implement, pass, commit `feat(forward): discord webhook alerts`.

### Task 4: PaperBroker (`broker.py`)

**Files:** Create `src/sts/forward/broker.py`, `tests/forward/test_broker.py`.

**Produces:**
```python
class Fill(TypedDict): price: float; fees: float; timestamp: str
class PaperBroker(ABC):
    @abstractmethod def fill_entry(self, symbol: str, date: dt.date, qty: int) -> Fill | None
    # Resting stop/target management is NOT broker-side this phase: exits are governed by the
    # daily-bar engine (pipeline upkeep) per prereg. Interface leaves room: no-op hooks
    # place_protective(row), cancel(entry_id) so an Alpaca/IBKR impl can slot in later.
class StubPaperBroker(PaperBroker):
    def __init__(self, get_open: Callable[[str, dt.date], float | None]): ...
    # fill_entry: price = actual session open via get_open (None → no fill yet, caller retries);
    # fees = price*qty*5/10_000 + 1.0  (entry side only; exit side fees applied at close in pipeline)
def cost_side(price: float, qty: int, bps: float = 5.0, per_order: float = 1.0) -> float
```
`get_open` in production reads the StudyStore bar for `date` if present, else `sts.data.fetch.fetch_daily(symbol, start=date)`'s row for `date` (yfinance returns today's partial row during the session; its `open` is final after 9:30 ET).

- [ ] Tests: stub fills at supplied open with correct fees; returns None when open unavailable; `cost_side` arithmetic (100 sh @ $50: 50*100*0.0005+1 = $3.50). Implement, pass, commit `feat(forward): PaperBroker interface + stub`.

### Task 5: Book state + charter checks (`book.py`)

**Files:** Create `src/sts/forward/book.py`, `tests/forward/test_book.py`.

**Interfaces — Consumes:** `Ledger` (Task 2), `sts.risk.position_size`. **Produces:**
```python
START_EQUITY = 100_000.0
@dataclass class BookState:
    book: str; equity: float; cash: float; open_rows: list[dict]
    @classmethod def from_ledger(cls, ledger: Ledger, book: str, marks: dict[str, float]) -> "BookState"
        # equity = cash + Σ qty*mark (mark = latest close; fallback entry_fill)
        # cash replayed from START_EQUITY over closed/open rows: -usd_deployed-fees at entry, +qty*exit_price-fees at exit
    def deployed_usd(self) -> float; def deployed_frac(self) -> float; def open_count(self) -> int
    def can_enter(self, symbol: str, notional: float, shared_blocked: set[str]) -> str | None
        # returns skip reason or None: "dup_symbol" (symbol in own book, or in shared_blocked for
        # the shared book's cross-family rule), "slot" (open_count>=8),
        # "deploy_cap" (deployed+notional > 0.80*equity)
    def size(self, entry: float, stop: float) -> int
        # risk.position_size(self.equity, entry, stop) — charter 0.75% risk + 15% notional cap live in risk.py
    def snapshot(self, date: dt.date) -> dict     # equity.jsonl row
def h1_throttle_room(ledger: Ledger, book: str, session_dates: list[dt.date]) -> int
    # 4 - (H1 entries FILLED OR QUEUED for this book over the trailing 5-session window incl. today) , min 0
```
- [ ] Tests: cash/equity replay over synthetic open+closed rows; each `can_enter` reason; `size` matches `risk.position_size` incl. 15% cap; throttle counts queued+filled across the rolling window (verify 4/5 exactly at the boundary). Implement, pass, commit `feat(forward): book state, charter checks, h1 throttle`.

### Task 6: EOD pipeline core (`pipeline.py`)

**Files:** Create `src/sts/forward/pipeline.py`, `tests/forward/test_pipeline.py`.

**Consumes:** everything above + `sts.study.h4_candidates.candidates_for`, `sts.calendar.last_completed_session`, `sts.catalyst.CatalystCalendar`, `risk.manage_bar`, `risk.Position`. **Produces:**
```python
def run_upkeep(ledger: Ledger, prices: dict[str, pd.DataFrame], asof: dt.date) -> list[dict]
    # For every open row and every session bar in (last_processed, asof]: rebuild risk.Position
    # (entry=entry_fill, stop=sl, target=tp1, opened=entry date, shares=qty) and apply
    # risk.manage_bar per bar → on exit append closed row (exit_reason from manage_bar verbatim;
    # fees_total += cost_side(exit); pnl_usd; r_net vs stop_initial with total fees).
    # Position.time-stop (15 sessions) comes free from manage_bar. Time-based sl updates: none
    # this phase (sl == stop_initial unless manage_bar semantics move it — they don't).
    # Then append per-book equity snapshots for asof and an "upkeep_done" control record.
    # Idempotent: skip if asof in ledger.processed_upkeep_dates(). Returns closed rows (for alerts).

def generate_signals(ledger: Ledger, prices, asof: dt.date, catalyst) -> dict
    # signal_date = asof (last completed session). Candidates via candidates_for("h2"|"h1",
    # prices, asof, asof+1day, catalyst) — entry_date will be the NEXT session's open;
    # candidates_for returns None-geometry events only when the next bar already exists, so for
    # live signals compute geometry manually: entry_ref = None until fill; stop/target from
    # signal-bar ATR anchored at a provisional entry = signal close (NOTE: backtest anchors
    # stop/target at actual next open — the fill job RE-ANCHORS stop/tp1 at the actual fill
    # price with the same ATR multiples, preserving backtest semantics exactly).
    # Ranking: H2 first sorted (signal_date, symbol); then H1 sorted by RANK_KEY
    # (is_seed DESC, rsi2_at_trigger, reclaim_wait_sessions, signal_date, symbol) — copy the
    # key from scripts/run_h4b_study.py:RANK_KEY.
    # For book in ("shared", "h1solo"): walk the queue (h1solo sees only H1), apply
    # can_enter / embargo (candidates_for already embargo-filters; belt-and-braces re-check) /
    # h1_throttle_room / size>0; append kind="candidate" (with qty, entry_price_range =
    # [close - 0.25*atr, close + 0.25*atr] rounded 2dp — display band only) or kind="skip"+reason.
    # Idempotent by (signal_date, book, entry_id). Returns {"queued": [...], "skipped": [...]}.

def detect_missed_sessions(ledger, asof) -> list[dt.date]
    # sessions between last upkeep_done and asof with no journal record → append kind="missed_session"
```
- [ ] **Step 1:** Tests with small synthetic price frames (pattern: build 300-bar frames like `tests/` already does for h1/h2 studies — reuse their fixture style): upkeep closes a position on a stop bar with reason `stop`; gap-open → `stop_gap`; target touch → `target`; 15-session → `time`; upkeep idempotent on re-run; signal gen orders H2 before H1, respects throttle=4/5, dup-symbol cross-family block in shared book but NOT in h1solo, skip records written with reasons; missed-session detection.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat(forward): EOD upkeep + signal generation pipeline`.

### Task 7: EOD job script (`scripts/forward_eod.py`)

**Files:** Create `scripts/forward_eod.py`. Modify `Makefile` (add `forward-eod`).

Sequence (with per-stage timing + ETA lines, resume-capable):
1. `sts.env.load()`; `asof = last_completed_session()`; exit 0 with log if journal already has `upkeep_done` for `asof` AND signals for `asof` (idempotent re-run).
2. Incremental fetch: for the 250-name roster (reuse `scripts/fetch_study_roster.py`'s store + `fetch_daily(symbol, start=last_date+1)` append pattern; budgeted, resumable, failures logged not fatal). Refresh earnings via existing catalyst fetch path if stale (>3 days).
3. `run_upkeep` → Discord `exit_alert` per close.
4. `generate_signals` → Discord `entry_alert` per queued candidate + `book_status` line; explicit "no candidates" message when queue empty (silence must be distinguishable from outage — prereg caveat).
5. `detect_missed_sessions` → Discord warning if any.
6. `sync.run_daily_sync()` (Task 9).
- [ ] Test: `--dry-run` mode (no Discord, no sync) runs against cached frames; second invocation logs no-op. Manual gate: run `--dry-run` for real `asof` on the actual roster cache. Commit `feat(forward): nightly EOD job`.

### Task 8: Open-fill job + monitor (`scripts/forward_fill.py`, `scripts/forward_monitor.py`)

**Files:** Create both scripts, `tests/forward/test_fill.py`. Modify `Makefile`.

`forward_fill.py` (run ≥9:31 ET on sessions): for each `kind="candidate"` signal whose entry session is today and whose `entry_id` has no ledger row: `StubPaperBroker.fill_entry` → if open not yet available, retry loop (60s, max 20 min, resumable); re-anchor `sl = risk.atr_stop(fill, atr_sig, 2.0)`, `tp1 = risk.atr_target(fill, atr_sig, 2.0)` (ATR value stored on the signal record at gen time); re-check `can_enter` + size at fill price against CURRENT book state (queue was sized on stale equity); append open ledger row (`entry_ref = fill` for stub — modeled next-open IS the session open, so slippage ≡ 0 as prereg notes; `entry_fill = fill`); Discord confirmation. Idempotent by `entry_id`.

`forward_monitor.py` (hourly 7:00–17:00 PT weekdays + the pre/post checks): open rows only (≤8+8 symbols); quotes via `yfinance.Ticker(...).fast_info` (batch); alert on `last ≤ sl` ("STOP TOUCHED — advisory; daily-bar engine governs"), `last ≥ tp1`, or pre/post move >3% vs prior close. Dedupe: journal `kind="monitor_alert"` per (entry_id, alert_type, date) so an alert fires once per day. Never writes ledger rows.

- [ ] Tests: fill idempotency (second run no-op); re-anchoring math; monitor dedupe logic (quote fetch monkeypatched). Commit `feat(forward): open-fill job and hourly advisory monitor`.

### Task 9: Drive sync (`sync.py`, `scripts/forward_sync.py`)

**Files:** Create `src/sts/forward/sync.py`, `scripts/forward_sync.py`, `tests/forward/test_sync.py`. Modify `Makefile`.

```python
FORWARD_FOLDER_ID = "1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5"
BACKTEST_FOLDER_ID = "1i11V4ooDMRQbbVSkwzwbFr7lKlOoNcEQ"
REMOTE = os.environ.get("STS_RCLONE_REMOTE", "gdrive:")

def _rc(args: list[str], folder_id: str) -> subprocess.CompletedProcess
    # ["rclone", *args, "--drive-root-folder-id", folder_id, "--retries", "3"]
def sync_ledgers(paths: LedgerPaths) -> None
    # MERGE-ONLY, remote is source of truth:
    # for f in (h1.jsonl, h2.jsonl, equity.jsonl, signals.jsonl):
    #   1. rclone copyto REMOTE:f  tmp/f.remote   (missing remote file → fresh start, ok)
    #   2. merged = journal.merge_lines(remote_lines, local_lines, key)   # remote first = remote precedence
    #      keys: (entry_id, seq) for family ledgers; (date, book) equity; (signal_date, book, entry_id|kind|date) signals
    #   3. SAFETY: assert set(remote_lines) ⊆ set(merged) — refuse to upload (raise SyncError,
    #      Discord alert) if any remote line would be lost. Never a destructive overwrite.
    #   4. write merged atomically to local f; rclone copyto f REMOTE:f
def push_backtest_artifacts() -> None
    # rclone copy runs/ REMOTE:runs + rclone copy docs/preregs REMOTE:preregs
    # --ignore-existing NOT used; plain copy (no --delete anything) → adds/updates only, never deletes
def run_daily_sync(paths) -> None   # sync_ledgers + push_backtest_artifacts, each failure alerted, non-fatal to caller
```
- [ ] Tests: merge precedence (remote wins collisions), superset safety check raises on simulated remote-line loss, `_rc` command construction (subprocess monkeypatched). Manual gate (executor runs): `rclone lsjson --drive-root-folder-id 1DIk5ZC... gdrive: --max-depth 1` to confirm which remote reaches the folders — if `gdrive:` lacks access try `bhat-trading-drive:` and record the working remote in `.env.example` as `STS_RCLONE_REMOTE`. Commit `feat(forward): merge-only Drive sync for ledgers + one-way backtest artifact push`.

### Task 10: Scheduling + end-to-end dry run + docs

**Files:** Create `deploy/launchd/com.sts.forward-eod.plist` (weekdays 17:30 PT), `com.sts.forward-fill.plist` (weekdays 06:31 PT), `com.sts.forward-monitor.plist` (hourly 07:00–17:00 PT weekdays), `deploy/launchd/install.sh` (idempotent `launchctl bootstrap gui/$UID`), each running `make forward-*` with logs to `logs/forward/`. Modify `docs/PLAN.md` (Phase-5 section: link this plan + operational runbook), `README.md` (forward ops section).

- [ ] End-to-end rehearsal (the verify gate): temporarily point `LedgerPaths` at `.scratch/ledger-rehearsal/`, run `forward_eod.py --asof <last Friday> --no-sync --no-discord`, then `forward_fill.py --asof <next session> --no-sync --no-discord` against cached bars, then a real single Discord test message and one real `forward_sync.py --dry-run` (rclone `--dry-run` flag pass-through). Confirm: signals ranked correctly, ledger rows validate, second runs are no-ops.
- [ ] `make test` fully green. Commit `feat(forward): launchd scheduling, runbook, e2e rehearsal`.

## Self-Review Notes

- Prereg coverage: ledgers/schema (T2), entry_id idempotency (T2/T8), slot-contention + H2-priority + RANK_KEY + throttle (T5/T6), h1solo book (T5/T6 book loop), broker stub + swap interface (T4), EOD job (T7), fill job (T8), monitor advisory-only (T8), Discord (T3), missed-session integrity (T6/T7), Drive merge-only (T9), all-deployments daily sync after signal gen + upkeep (T7 step 6), resumable/idempotent everywhere.
- Open design decision recorded (not in prereg, display-only): `entry_price_range = signal close ± 0.25×ATR`, 2dp — alert band only, never a fill constraint.
- Re-anchoring stop/tp1 at actual fill with locked ATR multiples = exactly `entry_geometry`'s backtest convention (stop/target computed off actual next-open entry with signal-bar ATR).
