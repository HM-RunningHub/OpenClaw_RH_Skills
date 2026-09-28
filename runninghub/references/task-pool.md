# Task Pool (batch / async workflows)

For **batch submission** or **long-running workflows**, use the task pool instead of
blocking on a single script call. It submits many jobs, runs them within a
concurrency budget, downloads results, and wakes this session when the batch drains.

Script: `python3 {baseDir}/scripts/rh_pool/pool.py`

## When to use

**Any workflow task goes here — a single one counts.** Do not look for a
standard-API endpoint for 语音克隆 / 数字人 / 文生图 workflows.

- User asks for a **workflow type** (语音克隆 / 数字人 / 文生图, any single job)
- User wants **several generations** at once ("跑 3 个", "批量", "都生成一遍")
- A task is **slow** and the user keeps chatting (video / digital human / 3D / music)
- User asks for **progress** on submitted work

The standard-API single-task flow in `SKILL.md` is only for endpoints that are
not pool workflow types.

## Task types

Named types live in `config/task-types.json` (copy `task-types.json.example` to
start). Each type maps friendly params to a workflow's node inputs.

```bash
# what is available / validate against archived workflow exports
python3 {baseDir}/scripts/rh_pool/pool.py workflow list
python3 {baseDir}/scripts/rh_pool/pool.py workflow validate
```

A type's file params accept **a local path** (uploaded automatically, cached),
an `api/...` id, or a URL.

## Submit

```bash
# one type
python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --type image-gen --param prompt="a cute puppy, 4K cinematic"

# a batch from a file (list of jobs)
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --from-file jobs.json
```

`jobs.json`:
```json
[
  {"type": "image-gen", "params": {"prompt": "..."}},
  {"type": "voice-clone", "params": {"text": "...", "referenceAudio": "/path/ref.m4a"}},
  {"type": "digital-human", "params": {"image": "/path/p.jpg", "audio": "/path/a.m4a", "text": "..."}}
]
```

`enqueue` returns `poolIds`. **Submitting is the whole job for you** — your turn
ends here. Do NOT poll `status`, sleep, or wait for completion in-loop; the pool
wakes this session when the batch drains. Tell the user it started (see
notification rules below), then end the turn.

To have the finished batch wake a specific session, set `OPENCLAW_SESSION_KEY`
before enqueueing; otherwise it wakes the configured default (`sessionKey`).

## Check progress

```bash
python3 {baseDir}/scripts/rh_pool/pool.py status              # counts + recent tasks
python3 {baseDir}/scripts/rh_pool/pool.py status --pool-id 7  # one task, incl. downloads
```

Statuses: `PENDING` → `DISPATCHED` → `SUCCESS` / `FAILED` / `SUBMIT_FAILED`.
`outstanding` is how much is still running.

Downloaded files land under `data/pool/output/<poolId>/...`; their paths are in
the task's `downloads_json`. **Deliver them with the `message` tool** exactly as
in `references/output-delivery.md`.

## Notification

On submit, the pool creates one polling automation (no LLM cost). When the batch
drains it wakes the originating session, which then reads `status` and delivers
the files. You do not manage this automation by hand.

Tune it in `config/skill-config.json` (copy the `.example`):

| Key | Meaning |
|-----|---------|
| `concurrency` | Max jobs in flight at once (default 3) |
| `pollIntervalSeconds` | Polling cadence (default 30) |
| `sessionKey` | Default wake-back session |
| `dataDir` | Ledger + outputs location |

## Requirements

`python3`, `curl`, and the `openclaw` CLI on `PATH` (or set `OPENCLAW_BIN`).
