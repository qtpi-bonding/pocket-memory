# Pocket Memory

Pocket Memory is PocketCoder's lightweight, local-first MCP memory service. It
stores mutable agent-authored observations and interpretations in SQLite, links
them through an ordinary many-to-many join, and retrieves them with FTS5 plus a
local multilingual embedding model. It does not call a generative LLM or decide
what is true.

The service is licensed under `AGPL-3.0-or-later`, like the PocketCoder
repository. The separately distributed `intfloat/multilingual-e5-small` model
is MIT-licensed and must ship with its upstream license and model provenance.

## Architecture

The crate deliberately uses conventional thin layers:

```text
MCP/HTTP -> service/use cases -> explicit SQLite repositories
                       |-> llama.cpp embedder worker
                       `-> FTS/vector candidate fusion and ranking
```

`schema.sql` is the complete schema for this unreleased backend. There is no
historical migration chain. Startup initializes an empty database or rejects a
database carrying another schema identifier.

## Agent MCP surface

Pocket Memory exposes eight tools to coding agents:

- `memory_create_observation`
- `memory_create_interpretation`
- `memory_link`
- `memory_unlink`
- `memory_get_observation`
- `memory_get_interpretation`
- `memory_list`
- `memory_search`

Every interpretation must remain linked to at least one observation. All links
are equal rows in the `interpretation_observations` many-to-many table; there is
no separate or privileged basis relationship. Interpretation creation accepts
either an existing observation or a new observation body, in which case both
records and their link are committed atomically. Additional existing
observations may be linked in the same transaction.

Body updates and record deletion are not exposed to agents by default. Setting
`POCKET_MEMORY_AGENT_EDITS=true` adds `memory_update` and `memory_delete`.

## Standalone use

- `POCKET_MEMORY_EXTRA_ALLOWED_HOSTS`: comma-separated Host header values accepted
  in addition to the built-in list.
- `Dockerfile.standalone` builds from this repository; `Dockerfile` keeps the
  paths of a parent repository that holds this one at `server/memory`.
- `scripts/import_markdown.py` imports a folder of Markdown notes once.

The identity header is attribution, not access control: anyone who can reach the
port can read and change every memory. Expose it only on a private network.

## Use it from coding agents

Agents with their own memory may save there instead of here: in a test, Claude
Code asked to "save this to memory" wrote a local file. Turn the built-in memory
off, and add to the agent's instruction file: "Search the memory tools first.
Save what you learn with them, not in files."

Set `HOST` to this service and `LABEL` to the identity header, which is base64url
without padding:

```sh
printf '%s' '{"version":1,"account_id":"shared","agent_profile_id":"laptop","agent_name":"Claude Code"}' \
  | base64 | tr '+/' '-_' | tr -d '=\n'
```

The header name is `X-PocketCoder-Memory-Context` for every tool. Settings below
come from each tool's documentation, read in November 2026. Only Claude Code was
tested here.

| Tool | Built-in memory | Turn it off |
| --- | --- | --- |
| Claude Code | On by default | `"autoMemoryEnabled": false` in `~/.claude/settings.json`, or `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (tested with 2.1.331), or the `/memory` toggle |
| Codex CLI | Off by default | Leave `features.memories` unset or false in `~/.codex/config.toml`. `memories.generate_memories = false` and `memories.use_memories = false` stop writing and reading |
| Antigravity | `/learn` saves only after approval. Other automatic knowledge: unconfirmed | No off switch found. Do not run `/learn` |
| OpenCode | None found in its configuration documentation | Nothing to turn off |

Add the server:

```sh
# Claude Code
claude mcp add --transport http memory http://HOST:8000/mcp --header "X-PocketCoder-Memory-Context: LABEL"
```

```toml
# Codex CLI: ~/.codex/config.toml
[mcp_servers.memory]
url = "http://HOST:8000/mcp"
http_headers = { "X-PocketCoder-Memory-Context" = "LABEL" }
```

Antigravity, in `~/.gemini/config/mcp_config.json`:

```json
{"mcpServers": {"memory": {"serverUrl": "http://HOST:8000/mcp", "headers": {"X-PocketCoder-Memory-Context": "LABEL"}}}}
```

OpenCode: see <https://opencode.ai/docs/mcp-servers/>. Use a remote server with
`"oauth": false` and the same header under `"headers"`.

Plain HTTP is only suitable over a private, encrypted network.

Sources: <https://code.claude.com/docs/en/memory>, <https://code.claude.com/docs/en/mcp>,
<https://learn.chatgpt.com/docs/customization/memories>,
<https://learn.chatgpt.com/docs/config-file/config-reference>,
<https://antigravity.google/docs/mcp>, <https://antigravity.google/docs/commands/learn/>.

## Model contract

- Upstream: `intfloat/multilingual-e5-small`
- Format: PocketCoder-produced Q8_0 GGUF
- Runtime: in-process llama.cpp CPU encoder
- Context: 512 tokens
- Pooling: mean
- Output: 384 dimensions, L2-normalized
- Query prefix: `query: `
- Stored-document prefix: `passage: `

The release artifact must be generated from pinned upstream and converter
revisions, validated against the upstream F32 model, checksum-pinned, and
bundled so production startup needs no network access.

For development, use the immutable
MIT Q8_0 artifact from `janusz-bit/multilingual-e5-small-gguf` commit
`57c0a8f1481a66ca991375e4f87311c9e4bd0cc5` with SHA-256
`3a98dd889ee152d923991c60df2fad21e39f7441a5ee302a0a050d5137993b60`.
`tests/model_compat.rs` verifies that the configured artifact loads through the
actual adapter and produces finite, normalized multilingual embeddings, and
`tests/model_reference.rs` compares them with upstream. Release
CI requires explicit model URL and checksum values so production can switch to
PocketCoder's independently reproduced artifact without runtime changes.

### Model delivery

The container build downloads the pinned GGUF, verifies its SHA-256, and copies
the model plus its MIT license and provenance into the final image. The deployed
service does not download the model at startup and does not need network access
to start or perform semantic retrieval. The current Q8_0 GGUF is approximately
126 MiB on disk.

### Measured memory footprint

Idle is the memory held while the service waits for work; it is not zero, because
the model stays loaded. The peak grows with the length of the text embedded, up to
the 512-token limit, and is not released afterwards.

Container memory measured on 2026-11-24, arm64 Debian Bookworm, release build,
bundled Q8_0 model, CPU only:

| State | Container memory |
| --- | ---: |
| Ready, before the first embedding | approximately 265 MiB |
| After a short note | approximately 270 MiB |
| After a note that fills the 512-token limit | approximately 760 MiB |

About 130 MiB of the total is file-backed model data that the operating system
can reclaim under pressure. Measurements on other architectures may differ.

Allow at least 1 GiB for the service. At 512 MiB it was killed while importing
long notes. These are service-level sizing numbers, not a whole-stack PocketCoder
memory requirement.

## Acknowledgements and provenance

[mcp-local-memory](https://github.com/Beledarian/mcp-local-memory) (MIT) was
consulted as design prior art, especially its independent FTS/vector candidate
retrieval and explicit FTS fallback. Pocket Memory does not copy its source and
does not adopt its graph, archivist, task, reinforcement, or extension models.
Its MIT license therefore remains a reference to the consulted project rather
than a license applied to Pocket Memory's original AGPL source.

Bundled Rust dependencies and native/model artifacts retain their respective
licenses. Release packaging must include the generated dependency license report
and the model's upstream license/provenance files.
