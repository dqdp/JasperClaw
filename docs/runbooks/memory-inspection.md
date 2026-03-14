# Runbook: Memory Inspection

## Purpose

Provide the canonical operator procedure for understanding why memory was or was
not retrieved or materialized without resorting to ad hoc code archaeology.

## When to use this runbook

Use this when any of the following is true:

- a user says the assistant forgot a durable fact
- memory retrieval appears noisy or empty
- a recent change may have altered extraction behavior
- you need to confirm whether a memory item was invalidated or deleted

## Key runtime signals

### Metrics

The main memory metrics are exported by `agent-api`:

- `agent_api_memory_retrieval_total`
- `agent_api_memory_retrieval_hits_total`
- `agent_api_memory_materialization_total`
- `agent_api_memory_candidate_total`
- `agent_api_memory_lifecycle_total`

Fetch only the memory-related subset:

```bash
docker compose exec -T agent-api \
  wget -qO- http://127.0.0.1:8080/metrics | grep '^agent_api_memory_'
```

Interpretation:

- high `memory_candidate_total{decision="skipped",reason="no_durable_signal"}`
  means extraction is intentionally rejecting the observed transcript shape
- `memory_retrieval_total{outcome="success"}` with low
  `memory_retrieval_hits_total` means retrieval runs are succeeding but not
  finding enough active semantic matches
- non-zero `memory_lifecycle_total{outcome="error"}` means an explicit
  invalidation or deletion attempt failed

### Structured logs

The main structured events are:

- `chat_memory_candidate_evaluation_completed`
- `chat_memory_materialization_completed`
- `chat_memory_retrieval_completed`
- `chat_memory_lifecycle_completed`

Filter recent memory events:

```bash
docker compose logs agent-api | rg 'chat_memory_(candidate|materialization|retrieval|lifecycle)'
```

If you have a specific request ID, filter by that first:

```bash
REQ_ID=req_example123
docker compose logs agent-api | rg "${REQ_ID}"
```

Interpretation:

- `chat_memory_candidate_evaluation_completed`
  - inspect `accepted_message_ids`
  - inspect `skip_reason_counts`
- `chat_memory_materialization_completed`
  - `outcome="skipped"` with `skip_reason="no_candidates"` means transcript was
    persisted but nothing matched the durable-signal extractor
  - `outcome="error"` means embedding or storage failed, but chat stayed
    fail-open
- `chat_memory_retrieval_completed`
  - inspect `retrieval_hit_ids`
  - inspect `retrieval_hit_scores`
  - `retrieval_hit_count=0` means retrieval completed but selected nothing
- `chat_memory_lifecycle_completed`
  - inspect `target_status`, `previous_status`, `current_status`, and
    `error_code`

## Canonical SQL checks

### 1. Inspect recent memory items

```bash
docker compose exec -T postgres psql -U assistant -d assistant <<'SQL'
SELECT
  id,
  status,
  source_message_id,
  conversation_id,
  created_at,
  updated_at,
  left(content, 120) AS content_preview
FROM memory_items
ORDER BY updated_at DESC
LIMIT 20;
SQL
```

Use this to confirm whether a fact exists at all and whether it is still
`active`, `invalidated`, or `deleted`.

### 2. Inspect recent retrieval runs and hits

```bash
docker compose exec -T postgres psql -U assistant -d assistant <<'SQL'
SELECT
  rr.id,
  rr.conversation_id,
  rr.request_id,
  rr.query_text,
  rr.status,
  rr.top_k,
  rr.latency_ms,
  rr.created_at
FROM retrieval_runs rr
ORDER BY rr.created_at DESC
LIMIT 10;

SELECT
  rh.retrieval_run_id,
  rh.memory_item_id,
  rh.rank,
  rh.score,
  left(mi.content, 120) AS content_preview
FROM retrieval_hits rh
JOIN memory_items mi ON mi.id = rh.memory_item_id
ORDER BY rh.created_at DESC, rh.rank ASC
LIMIT 20;
SQL
```

Use this to distinguish:

- retrieval never ran
- retrieval ran but returned no hits
- retrieval returned hits, but they were poor choices

### 3. Inspect the source transcript for a memory item

```bash
docker compose exec -T postgres psql -U assistant -d assistant <<'SQL'
SELECT
  mi.id AS memory_item_id,
  mi.status,
  mi.source_message_id,
  m.conversation_id,
  m.role,
  m.source,
  m.created_at,
  m.content
FROM memory_items mi
JOIN messages m ON m.id = mi.source_message_id
WHERE mi.id = 'mem_replace_me';
SQL
```

Use this when you need to confirm whether the stored memory really came from the
expected transcript turn.

## Common failure shapes

### Durable fact never materialized

Expected signals:

- `chat_memory_candidate_evaluation_completed` shows only skipped decisions
- `chat_memory_materialization_completed` shows `skip_reason="no_candidates"`
- the source transcript exists in `messages`, but no corresponding row exists in
  `memory_items`

Most likely cause:

- the utterance did not match the current durable-signal extractor

### Memory exists but retrieval stays empty

Expected signals:

- memory item exists and is `active`
- retrieval runs exist
- `retrieval_hit_count=0` or hits are consistently too weak

Most likely causes:

- the latest user turn is not semantically close enough to the stored memory
- `MEMORY_MIN_SCORE` is too strict for the current embedding model

### Memory was present but later disappeared from retrieval

Expected signals:

- row exists in `memory_items`
- `status` is `invalidated` or `deleted`
- a matching `chat_memory_lifecycle_completed` event exists

Most likely cause:

- an explicit lifecycle transition removed the item from the active retrieval set

## Important non-goals

This runbook does not define:

- how to restore a lost database
- how to change memory schema
- how to widen extraction policy

Use the backup, restore, or planning documents for those tasks instead.
