---
name: say-then-publish
description: Self-contained local Xiaohongshu creator workspace. Use when a user asks to initialize or start Say Then Publish, turn a conversation or Markdown draft into Xiaohongshu image cards, revise or format a project, add Agent-generated illustrations, export cards, or optionally synchronize with collaborators. The Skill bundle contains the application code and must not clone GitHub.
---

# Say Then Publish

Turn what the user says into publish-ready Xiaohongshu cards. The bundled app is the source of truth; the web UI is the visual workspace and the CLI is the safe mutation interface.

## First initialization

Resolve `SKILL_ROOT` as the directory containing this `SKILL.md`. Never search GitHub or clone another repository: the complete application is already under `assets/app/`.

On the first “初始化” or “启动” request, collect exactly two values if they are not already configured:

1. The user's Xiaohongshu account display name.
2. The absolute folder where they normally keep social-content files.

The platform is always `小红书`; do not ask for it. Recommend a dedicated local folder such as `~/Documents/小红书内容` when the user has no preference.

Run:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" init \
  --account-name "用户的小红书名称" \
  --content-dir "/absolute/path/to/content"
```

Initialization copies the embedded app into `<content-dir>/.say-then-publish/app`, creates the Python environment, starts the local service and opens the workspace. Personal settings are written under the user's home/content folders, never back into the shareable Skill.

## Personal creator memory

The Skill and the user's memory are deliberately separate. `SKILL_ROOT` contains only reusable behavior; identity, device/account notes, layout preferences and durable feedback live in `~/.say-then-publish/creator-memory.json` (or `$SAY_THEN_PUBLISH_HOME/creator-memory.json`). Never write personal memory back into this Skill.

Before drafting, revising, formatting or illustrating, read the current memory:

```bash
python3 "$SKILL_ROOT/scripts/creator_memory.py" show
```

When the user explicitly says “记住”, states a durable preference, or corrects the same kind of output, save one concise reusable rule—not the whole draft:

```bash
python3 "$SKILL_ROOT/scripts/creator_memory.py" remember \
  --category layout \
  --key "高亮密度" \
  --value "每张卡只高亮一个最重要结论"
```

Use `identity` for public social-media names, `device` for non-secret device/account labels, and `layout`, `writing`, `visual`, or `workflow` for preferences. Never store passwords, verification codes, cookies, tokens, API keys or private draft bodies. If the user asks to forget something, run `forget` with its category and key.

## Start and inspect

For later “启动” requests:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" start
```

Check status without guessing:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" status
```

Use the wrapper for all project operations:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli list
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli get PROJECT_ID
```

## Direct Agent layout rule

Do the layout work yourself. Never call an external layout or polish AI, never use `/api/ai/optimize-layout`, and never direct the user to an “AI 优化排版” button.

When asked to 优化排版、整理重点、拆卡 or make the content easier to scan:

1. Read personal creator memory, then read the newest project revision with `cli get`.
2. Preserve meaning, facts, links and image markers unless rewriting is explicitly requested.
3. Apply remembered preferences plus the layout language in [references/layout-language.md](references/layout-language.md).
4. Update through the conditional CLI.
5. Read the saved revision again and report local/cloud confirmation separately.

## Project workflow

1. Run `status` and confirm the local service is healthy.
2. Run `cli list`; never guess an ID when titles repeat.
3. Run `cli get PROJECT_ID` before every mutation.
4. Create or update through the wrapper. Never edit project JSON, browser storage or cloud rows directly.
5. Treat `localSaved` and `cloudSynced` as separate gates.
6. On `DRAFT_VERSION_CONFLICT`, stop changing the original and report both preserved versions.

Create from Markdown:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli create \
  --title "小红书选题" \
  --from-file "/absolute/path/draft.md"
```

Update safely:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli update PROJECT_ID \
  --from-file "/absolute/path/revised.md"
```

Set publication state:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli update PROJECT_ID --published
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli update PROJECT_ID --unpublished
```

## Illustrations

Use an image-generation capability already available to the Agent host. Do not search public image libraries as a fallback. Preserve the user's requested visual style and keep important text out of raster images unless explicitly requested.

Insert generated images only through a unique exact anchor:

```bash
python3 "$SKILL_ROOT/scripts/bootstrap.py" cli add-image PROJECT_ID \
  --file "/absolute/path/generated.png" \
  --after-line "## 01 完整且唯一的小标题" \
  --name "01-配图.png" \
  --width-percent 100
```

If the line is missing or duplicated, stop and ask for a better anchor instead of guessing.

## Privacy boundary

- Keep the Skill bundle generic. Never write a user's account name, paths, drafts, images or credentials into `SKILL_ROOT`.
- Store personal onboarding data only in the installed local workspace and `~/.say-then-publish/`.
- Never print `.env`, Supabase secrets, object-storage keys or image Base64 data.
- Cloud collaboration is optional. Zero configuration must remain fully usable locally.
- Opening or exporting is not proof of publication.

## Completion report

Report the project title, ID, revision, published/unpublished state, local save result and cloud confirmation. Mention preserved conflict-copy IDs when present.
