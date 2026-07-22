create table if not exists public.write_then_publish_projects (
    workspace_id text not null,
    project_id text not null,
    title text not null default '',
    project_data jsonb not null default '{}'::jsonb,
    updated_at_ms bigint not null,
    is_active boolean not null default false,
    created_at timestamptz not null default now(),
    synced_at timestamptz not null default now(),
    primary key (workspace_id, project_id),
    constraint write_then_publish_projects_data_object
        check (jsonb_typeof(project_data) = 'object'),
    constraint write_then_publish_projects_updated_at_nonnegative
        check (updated_at_ms >= 0)
);

create index if not exists write_then_publish_projects_workspace_updated_idx
    on public.write_then_publish_projects (workspace_id, updated_at_ms desc);

create unique index if not exists write_then_publish_projects_one_active_idx
    on public.write_then_publish_projects (workspace_id)
    where is_active;

alter table public.write_then_publish_projects enable row level security;
revoke all on table public.write_then_publish_projects from anon, authenticated;
grant select, insert, update, delete on table public.write_then_publish_projects to service_role;

comment on table public.write_then_publish_projects is
    'Write Then Publish team drafts. Image binaries live in private TOS objects; JSON stores stable object references only.';

create table if not exists public.write_then_publish_assets (
    asset_id uuid primary key,
    workspace_id text not null,
    sha256 text not null,
    object_key text not null,
    original_name text not null default 'image',
    mime_type text not null,
    byte_size bigint not null,
    created_at timestamptz not null default now(),
    last_used_at timestamptz not null default now(),
    deleted_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    constraint write_then_publish_assets_sha256_hex
        check (sha256 ~ '^[0-9a-f]{64}$'),
    constraint write_then_publish_assets_size_nonnegative
        check (byte_size >= 0),
    constraint write_then_publish_assets_metadata_object
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists write_then_publish_assets_workspace_created_idx
    on public.write_then_publish_assets (workspace_id, created_at desc)
    where deleted_at is null;

create unique index if not exists write_then_publish_assets_live_sha_idx
    on public.write_then_publish_assets (workspace_id, sha256)
    where deleted_at is null;

create unique index if not exists write_then_publish_assets_live_object_idx
    on public.write_then_publish_assets (object_key)
    where deleted_at is null;

alter table public.write_then_publish_assets enable row level security;
revoke all on table public.write_then_publish_assets from anon, authenticated;
grant select, insert, update, delete on table public.write_then_publish_assets to service_role;

comment on table public.write_then_publish_assets is
    'Persistent TOS asset library. Removing an image token from draft text never deletes this row or its TOS object.';
