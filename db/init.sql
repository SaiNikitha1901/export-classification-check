-- Schema from shared contract A.8. Owner: Member 1.
-- Columns marked (M1 additive) are extra to A.8 and documented in docs/contract_changes.md.

CREATE TABLE IF NOT EXISTS runs (
    run_id          uuid PRIMARY KEY,
    client_id       text,
    correlation_id  text,
    status          text NOT NULL CHECK (status IN ('queued','running','completed','escalated','degraded','failed')),
    request         jsonb NOT NULL,
    result          jsonb,
    prompt_version  text,
    cache_hit       boolean NOT NULL DEFAULT false,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    -- (M1 additive)
    cache_key       text,                 -- whole-run cache key (D7)
    cache_stored    boolean NOT NULL DEFAULT false,
    cached_from     uuid,                 -- original run when cache_hit = true
    trace_context   jsonb,                -- W3C traceparent of the submit span, so the worker joins the same trace
    callback_url    text,
    callback_state  text CHECK (callback_state IN ('pending','delivered','failed')),
    callback_attempts int NOT NULL DEFAULT 0,
    callback_next_at  timestamptz
);
CREATE INDEX IF NOT EXISTS runs_status_idx ON runs (status);
CREATE INDEX IF NOT EXISTS runs_created_idx ON runs (created_at);
CREATE INDEX IF NOT EXISTS runs_callback_idx ON runs (callback_state) WHERE callback_state = 'pending';
CREATE INDEX IF NOT EXISTS runs_cache_fill_idx ON runs (status) WHERE cache_key IS NOT NULL AND NOT cache_stored AND NOT cache_hit;

CREATE TABLE IF NOT EXISTS run_steps (
    id                bigserial PRIMARY KEY,
    run_id            uuid NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_no           int NOT NULL,
    agent             text NOT NULL,
    kind              text NOT NULL CHECK (kind IN ('llm','tool','verify','guardrail','route')),
    name              text,
    input             jsonb,
    output            jsonb,
    status            text,
    latency_ms        int,
    prompt_tokens     int,
    completion_tokens int,
    cost_usd          numeric,
    prompt_version    text,
    started_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS run_steps_run_idx ON run_steps (run_id, step_no);

CREATE TABLE IF NOT EXISTS quarantine (
    id          uuid PRIMARY KEY,
    client_id   text,
    received_at timestamptz NOT NULL DEFAULT now(),
    payload     jsonb,
    errors      jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS quarantine_received_idx ON quarantine (received_at);

CREATE TABLE IF NOT EXISTS feedback (
    id           bigserial PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    satisfactory boolean NOT NULL,
    reason       text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id)  -- (M1 additive) one feedback per run
);

CREATE TABLE IF NOT EXISTS eval_scores (
    id          bigserial PRIMARY KEY,
    run_id      uuid,
    source      text NOT NULL CHECK (source IN ('batch','live')),
    scenario_id text,
    metric      text NOT NULL,
    value       numeric,
    label       text,
    scored_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eval_scores_metric_idx ON eval_scores (metric, scored_at);
