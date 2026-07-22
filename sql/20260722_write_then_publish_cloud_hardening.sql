alter table public.write_then_publish_assets
    add column if not exists delete_pending_at timestamptz,
    add column if not exists delete_error text;

comment on column public.write_then_publish_assets.delete_pending_at is
    'Durable two-phase marker. The row is hidden first, then its TOS object is deleted and deleted_at is finalized.';

create or replace function public.sync_write_then_publish_projects(
    p_workspace_id text,
    p_active_id text,
    p_projects jsonb
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if p_workspace_id is null or btrim(p_workspace_id) = '' then
        raise exception 'workspace_id is required';
    end if;
    if jsonb_typeof(p_projects) is distinct from 'array' then
        raise exception 'projects must be a JSON array';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(p_workspace_id, 0));

    insert into public.write_then_publish_projects (
        workspace_id,
        project_id,
        title,
        project_data,
        updated_at_ms,
        is_active,
        synced_at
    )
    select
        p_workspace_id,
        incoming.project_id,
        coalesce(incoming.title, ''),
        coalesce(incoming.project_data, '{}'::jsonb),
        incoming.updated_at_ms,
        false,
        coalesce(incoming.synced_at, now())
    from jsonb_to_recordset(p_projects) as incoming (
        project_id text,
        title text,
        project_data jsonb,
        updated_at_ms bigint,
        synced_at timestamptz
    )
    where incoming.project_id is not null
      and incoming.updated_at_ms is not null
    on conflict (workspace_id, project_id) do update
    set title = excluded.title,
        project_data = excluded.project_data,
        updated_at_ms = excluded.updated_at_ms,
        synced_at = excluded.synced_at
    where excluded.updated_at_ms > write_then_publish_projects.updated_at_ms;

    update public.write_then_publish_projects
    set is_active = false
    where workspace_id = p_workspace_id
      and is_active;

    if p_active_id is not null then
        update public.write_then_publish_projects
        set is_active = true
        where workspace_id = p_workspace_id
          and project_id = p_active_id;
    end if;
end;
$$;

revoke all on function public.sync_write_then_publish_projects(text, text, jsonb)
    from public, anon, authenticated;
grant execute on function public.sync_write_then_publish_projects(text, text, jsonb)
    to service_role;
