---
name: write-then-publish
description: Operate the local-first Write Then Publish creator workspace through its stable CLI. Use this skill whenever the user asks Codex to create, read, revise, synchronize, open, or mark a Write Then Publish project as published or unpublished. Also use it for requests to turn a local Markdown draft into a shared project that the cloud web collaborator can continue editing. Do not edit runtime-data/project-store.json directly.
compatibility: Requires Python 3 and the local Write Then Publish service in this repository.
---

# Write Then Publish

Use the product as the source of truth. Codex is one local client of the same project data that the browser and cloud collaborator use.

## Stable entrypoint

From the repository root, call:

```bash
.venv/bin/python scripts/wtp.py <command>
```

All commands return JSON. Read that JSON instead of inferring success from an exit code or a clicked browser control.

If the service is unavailable, start it without forcing a browser window:

```bash
WTP_OPEN_BROWSER=0 zsh scripts/start-server.zsh
```

Keep the service process running while completing the requested operations.

## Workflow

1. Run `status` and confirm the local service is healthy.
2. Use `list` to resolve the project. Do not guess an ID from a title when multiple projects match.
3. Use `get PROJECT_ID` before editing so the update is based on the newest local revision.
4. Create or update through the CLI. Never edit `runtime-data/project-store.json`, browser storage, Supabase rows, or TOS objects directly.
5. Read `localSaved` and `cloudSynced` from the response.
6. Report “已同步到云端” only when `cloudSynced` is `true` for the returned project revision.
7. If `cloudSynced` is false, preserve the local result and state plainly that the cloud version is not confirmed.
8. If the command exits with code 3 or returns `DRAFT_VERSION_CONFLICT`, stop updating that original project. Read the current project and the returned `conflictProject`; tell the user both versions were preserved and ask which content should become the main project.

## Common commands

List and inspect:

```bash
.venv/bin/python scripts/wtp.py list
.venv/bin/python scripts/wtp.py get PROJECT_ID
```

Create a shared project from Markdown:

```bash
.venv/bin/python scripts/wtp.py create \
  --title "项目标题" \
  --from-file "/absolute/path/draft.md"
```

Update an existing project safely:

```bash
.venv/bin/python scripts/wtp.py update PROJECT_ID \
  --from-file "/absolute/path/revised.md"
```

Update the simple publication state:

```bash
.venv/bin/python scripts/wtp.py update PROJECT_ID --published
.venv/bin/python scripts/wtp.py update PROJECT_ID --unpublished
```

Open the web workspace for visual review:

```bash
.venv/bin/python scripts/wtp.py open PROJECT_ID
```

## Agent illustration workflow

The web editor intentionally does not search public image libraries. When the user asks for illustrations, the Agent owns the workflow:

1. Run `get PROJECT_ID` and read the newest content and revision.
2. Decide which exact sections genuinely need an image. Do not insert decorative filler into every card.
3. Use the runtime-native image generation capability when available (for example Codex `imagegen`). Keep important text out of the generated raster unless the user explicitly requests text in the image.
   - If the user says to use an established visual direction such as “小黑 style”, preserve that direction in the image-generation prompt and use Codex's native generator; do not replace it with public-image search.
4. Save each generated PNG, JPEG, or WebP to a real local file.
5. Insert it through the CLI using a unique, exact line from the current draft as the anchor:

```bash
.venv/bin/python scripts/wtp.py add-image PROJECT_ID \
  --file "/absolute/path/generated.png" \
  --after-line "## 01 这一节的完整标题" \
  --name "01-这一节的配图.png" \
  --width-percent 100
```

Use `--before-line` when the image belongs before a section, or `--at-end` only when the user explicitly wants an ending image. The anchor must match one full line exactly and occur once; the CLI refuses ambiguous positions instead of guessing.

After every insertion, read `image.marker`, `project.updatedAt`, `localSaved`, and `cloudSynced` from the response. Run `get` again and verify that the marker is at the requested location and the image exists in `project.data.images`. Report cloud visibility only when `cloudSynced` is `true`.

## Conflict semantics

The product tracks the cloud revision from which a local edit started. When the local and cloud sides both change from that common revision, synchronization keeps the cloud collaborator's version under the original project ID and creates a separate local conflict project titled `（冲突副本）`.

This is a safety result, not a failed preservation. Do not automatically merge prose or force one side over the other. Compare both versions first; only apply a chosen merge after the user requests it.

## Boundaries

- Never paste a local absolute image path into Markdown. Use `add-image`; it embeds the bytes into the conditional project revision, after which cloud sync uploads the asset to private TOS when available.
- `.env`, access credentials, Supabase secrets, and TOS keys must never appear in command output or chat.
- A locally saved result is useful but is not the same as a cloud-confirmed result.
- Opening the web UI is for visual review. Project mutation still goes through the CLI so revision checks remain active.

## Completion report

Return the project title, project ID, new revision, publication state, local save result, and cloud confirmation. Mention a conflict copy ID whenever one exists.
