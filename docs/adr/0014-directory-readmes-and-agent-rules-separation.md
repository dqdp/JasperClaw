# ADR 0014: Use `README.md` for Directory Indexes and Reserve `AGENTS.md` for Agent Rules

- Status: Accepted
- Date: 2026-03-12

## Context

The repository is large enough that agents and humans both need fast local navigation.

Existing documentation explains architecture, contracts, and runbooks, but many directories do not have a short local index that answers:

- why this directory exists
- which file to open first
- when a specific file or child directory matters

At the same time, `AGENTS.md` already has a special meaning in this repository: it carries behavior rules, scope limits, and workflow expectations for the coding agent.

If directory navigation is mixed into `AGENTS.md`, navigation and policy will drift together and become harder to trust.

## Decision

Use `README.md` as the canonical directory index file.

Reserve `AGENTS.md` for agent-specific working rules only.

## Directory index rules

Each meaningful non-hidden directory should contain a short `README.md` when it helps a contributor or agent decide where to look next.

Each such `README.md` should:

- state the directory purpose in one or two short sentences
- identify the primary entry point with a `Start here` section when one exists
- list important files and child directories with a short `open when` cue
- prefer navigation intent over detailed content summaries
- call out legacy or non-canonical paths explicitly when relevant

Each directory index should stay concise.

The goal is local navigation, not a second architecture document.

## `AGENTS.md` rules

`AGENTS.md` should exist only where local agent instructions are actually needed.

Examples:

- edit constraints for a risky subsystem
- verification expectations for a directory
- concurrency, ABI, or runtime hazards that must shape implementation work

`AGENTS.md` should not be used as the default directory map.

## Scope rules

Apply this index convention to ordinary repository directories.

Do not add these index files to directories whose names begin with `.`.

Do not add them to generated or cache directories such as:

- `__pycache__`
- `.pytest_cache`
- virtual environments
- tool cache directories

## Consequences

### Positive

- agents can navigate from local context instead of repeatedly reopening distant top-level docs
- humans get the same lightweight map without reading agent-specific policy
- navigation guidance and behavioral rules remain separate and easier to maintain

### Negative

- directory indexes add maintenance overhead
- stale indexes become misleading if they are not updated with structural changes

## Maintenance rule

When a directory gains or loses an important file or child directory, update the local `README.md` in the same change when practical.
