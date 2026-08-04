---
name: write-then-publish
description: Say Then Publish — turn a conversation into publish-ready social image cards, all locally. Use this skill whenever the user, after chatting through an idea/recap/opinion in any agent window, wants it turned into 图文卡片; or asks to create, read, revise, synchronize, open, or mark a project as published/unpublished; or asks to 配图 / add illustrations to a project. Also use it to turn a local Markdown draft into a shared project a cloud web collaborator can keep editing. Do not edit runtime-data/project-store.json directly.
compatibility: Requires Python 3 and the local Write Then Publish service in this repository.
---

# Say Then Publish

The user talks; this skill turns the conversation into publish-ready image cards. You are one local client of the same project data the browser and cloud collaborator use — the product is the source of truth.

## You understand the card layout language

Don't just dump text into a card. This project exposes the 图文卡片 layout language as a stable interface, and you are expected to typeset like an editor would — that is the whole point of "say then publish":

- `**加粗**` for the one main conclusion of a card.
- `{{color:#RRGGBB|文字}}` to color a key phrase; `{{bg:#RRGGBB|文字}}` to highlight (yellow `#fff3a3` is the common default).
- `# 大标题` / `## 小标题` for structure; a blank line splits paragraphs; put each card's content together so pagination lands cleanly.
- Keep highlights sparing: emphasize the numbers, results, and turns — not whole sentences.

Judge where emphasis belongs from the meaning, then write it into the Markdown. Producing well-emphasized, correctly paginated cards in one pass is the value you add over a human doing it by hand.

## Private creator memory

This repository Skill is also personalized through a separate local memory file. Before drafting, revising, formatting or illustrating, read it:

```bash
.venv/bin/python skill-package/say-then-publish/scripts/creator_memory.py show
```

When the user explicitly asks you to remember a public social-media name, a non-secret device/account label, or a durable layout/writing/visual/workflow preference, save one concise rule:

```bash
.venv/bin/python skill-package/say-then-publish/scripts/creator_memory.py remember \
  --category layout \
  --key "高亮密度" \
  --value "每张卡只高亮一个最重要结论"
```

The memory lives at `~/.say-then-publish/creator-memory.json`, outside this repository and outside every shareable zip. Never commit or bundle it. Never store passwords, verification codes, cookies, tokens, API keys or full private drafts. Use `forget` when the user asks to remove a remembered item.

## Agent-native layout rule

Do layout work directly through the Markdown interface above. Never call an external layout/polish AI, never use `/api/ai/optimize-layout`, and never tell the user to look for an “AI 优化排版” button. That web entry has intentionally been removed.

When the user asks to 优化排版、整理重点、拆成卡片 or make the draft easier to scan:

1. Read private creator memory, then read the newest project revision with `get`.
2. Preserve the user's meaning and image markers unless they explicitly ask for rewriting.
3. Apply remembered preferences, headings, bold, sparse color/background highlights and deliberate page breaks yourself.
4. Write the result with the conditional `update` command.
5. Read the saved revision again and report local/cloud confirmation separately.

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

## Agent illustration workflow（配图 / 自动配图）

The web editor intentionally does not search public image libraries. When the user asks to 配图 / add illustrations, the Agent owns the workflow — **but check for the 小黑 image-generation skill first.**

### Step 0 — Pre-check: is the 小黑 skill installed?

Do NOT bundle, download, or install it yourself. Only check, then either proceed or hand the user an install link.

Look for a 小黑 (xiaohei) image skill in the standard skill directories:

```bash
ls -d ~/.claude/skills/* ~/.codex/skills/* ~/.agents/skills/* ~/.grok/skills/* 2>/dev/null \
  | grep -iE '小黑|xiaohei|xiao-?hei'
```

- **Not found** → stop before generating. Tell the user the 小黑 生图技能 is required for 配图 and give them the install link so they can set it up in one step, then continue once it is installed:

  > 配图需要先安装「小黑生图技能」。安装地址：`<TODO: 小黑生图技能安装地址>`
  > 装好后再对我说一次「帮我配图」即可。

  （Replace the placeholder with the real 小黑 skill install URL. The check above matches by name; adjust the pattern if the installed skill uses a different identifier.）

- **Found** → proceed to Step 1 and call that skill to generate images.

### Steps 1–5 — generate and insert

1. Run `get PROJECT_ID` and read the newest content and revision.
2. Decide which exact sections genuinely need an image. Do not insert decorative filler into every card.
3. Call the installed 小黑 生图技能 to generate the images, preserving the "小黑 style" visual direction in the prompt. Keep important text out of the generated raster unless the user explicitly requests text in the image. Do not fall back to public-image search.
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
