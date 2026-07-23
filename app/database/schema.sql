-- =====================================================================
-- Personal Productivity & Task Execution Agent — database schema
-- Postgres (Supabase) + pgvector. Idempotent: safe to run repeatedly.
-- =====================================================================

create extension if not exists vector;

-- ---------- enums ----------------------------------------------------
do $$ begin
    create type task_priority as enum ('Low', 'Medium', 'High', 'Critical');
exception when duplicate_object then null; end $$;

do $$ begin
    create type task_status as enum ('Pending', 'In Progress', 'Blocked', 'Completed', 'Cancelled');
exception when duplicate_object then null; end $$;

-- ---------- tasks ----------------------------------------------------
create table if not exists tasks (
    id            uuid primary key default gen_random_uuid(),
    title         text not null,
    description   text            default '',
    priority      task_priority   not null default 'Medium',
    status        task_status     not null default 'Pending',
    due_date      date,
    tags          text[]          not null default '{}',
    source        text            default 'user',   -- user | meeting_notes | ...
    notes         text            default '',
    created_date  timestamptz     not null default now(),
    updated_date  timestamptz     not null default now()
);

-- ---------- notes (semantic-searchable) ------------------------------
create table if not exists notes (
    id            uuid primary key default gen_random_uuid(),
    title         text not null,
    content       text not null,
    category      text            default 'general',
    tags          text[]          not null default '{}',
    embedding     vector(384),                       -- all-MiniLM-L6-v2
    created_date  timestamptz     not null default now(),
    updated_date  timestamptz     not null default now()
);

-- ---------- execution_logs (12 fields / run) -------------------------
create table if not exists execution_logs (
    run_id          uuid primary key default gen_random_uuid(),
    user_request    text not null,
    model           text,
    tools_called    jsonb not null default '[]',
    tool_args       jsonb not null default '[]',
    tool_results    jsonb not null default '[]',
    approval_status text,                              -- none | approved | rejected | mixed
    errors          jsonb not null default '[]',
    start_time      timestamptz not null default now(),
    end_time        timestamptz,
    duration_ms     integer,
    final_outcome   text                               -- success | partial | failed | rejected
);

-- ---------- auto-update updated_date on write ------------------------
create or replace function set_updated_date() returns trigger as $$
begin
    new.updated_date = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_tasks_updated on tasks;
create trigger trg_tasks_updated before update on tasks
    for each row execute function set_updated_date();

drop trigger if exists trg_notes_updated on notes;
create trigger trg_notes_updated before update on notes
    for each row execute function set_updated_date();

-- ---------- indexes --------------------------------------------------
create index if not exists tasks_status_idx   on tasks (status);
create index if not exists tasks_priority_idx on tasks (priority);
create index if not exists tasks_due_idx      on tasks (due_date);
-- HNSW cosine index for semantic note search (no training step needed).
create index if not exists notes_embedding_idx on notes
    using hnsw (embedding vector_cosine_ops);
