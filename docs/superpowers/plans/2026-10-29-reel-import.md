# Reel Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan one task at a time. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import reel URLs and author usernames from changing Instagram JSON exports with a reusable, sandboxed Python parser.

**Architecture:** The host tries the saved parser before it calls the LLM. Monty runs the parser, which returns actual reel URLs and author usernames. The host checks the output contract, applies collection rules, and deduplicates results. If the parser is missing or incompatible, the existing agent generates and tries a replacement.

**Tech Stack:** Existing Python, Pydantic, agent tools, and unittest. Installed `pydantic-monty` provides sandbox execution.

**Spec:** The design agreed in this conversation, recorded under Scope and Contract below.

## Global Constraints

- Assume valid JSON exports. Collect Instagram reels only.
- Preserve a reel when its author is unknown. Return `author_username: null`.
- Trust the generated parser to identify the correct records and URL-author relationships.
- Use a saved Python file until its extraction assumptions fail.
- Run generated code through Monty. Expose no host functions, mounts, network, or environment access.
- Keep the existing weather command available.
- Do not add inferred input schemas, source-reference contracts, record accounting, a selector language, or a parser registry.
- Preserve the existing untracked `json_examples/` and `tests/` content.
- Preserve unrelated edits in the working tree.
- Preserve existing `@beartype` decorators and apply them to new functions and methods.
- Execute inline, one task at a time. Each implementation task forms one focused commit if commits are requested.

## Review Focus

- A parser returns invalid field types or unexpected URLs. Task 1 must reject these results.
- A caption contains another reel URL, or labels change order. Task 3 must preserve the two supplied URL-author relationships.
- An author is missing or ambiguous. Tasks 1 and 3 must retain the reel with a null author.
- Generated code loops forever or requests a host file. Task 2 must stop it without replacing the saved parser.
- A cached parser works, or every replacement fails. Tasks 3 and 4 must avoid unnecessary LLM calls and preserve the working file.

## Scope and Contract

The generated function has one entry point: `parse(data)`.
It returns a list of plain objects with actual URL and author values.

```python
[
    {
        "url": "https://www.instagram.com/reel/DS-q1TClQuu/",
        "author_username": "theanomalyvault",  # None when unknown or ambiguous
    }
]
```

The parser handles label matching and other format-specific relationships in Python.
It raises an error when its structural assumptions fail.
A missing or ambiguous author remains an accepted result with a null username.

The host checks a list of `Reel` objects through Pydantic.
Each object requires `url: str` and `author_username: str | None`.
A non-null username must be nonempty.
The host keeps Instagram `/reel/<id>/` URLs and excludes Instagram `/p/<id>/` URLs.
Malformed or unexpected URLs cause an error.

The public output contains `url` and `author_username` only.
Normalize URLs to HTTPS, the `www.instagram.com` host, and a trailing slash. Remove query strings and fragments.
Preserve shortcode case.
Deduplicate reels by URL after collection rules. Prefer a known author over a null author for the same reel.
If duplicate records disagree about the author, retain the reel with a null author.

An empty output list is accepted.
The host does not independently detect omitted records or incorrect URL-author relationships.
The supplied examples establish the intended relationships through regression tests.
Do not describe successful validation as proof of complete semantic correctness.

## Files

| File | Responsibility |
|---|---|
| `src/reels_ripper_agent/reels.py` | One output model, collection rules, and deduplication |
| `src/reels_ripper_agent/parser.py` | Monty execution and saved parser files |
| `src/reels_ripper_agent/tools/reel_tools.py` | Input inspection, candidate execution, and existing agent integration |
| `src/reels_ripper_agent/agent.py` | Agent loop and structured STOP handling |
| `src/reels_ripper_agent/__init__.py` | File import command and final JSON output |
| `tests/test_reels.py` | Output checks, collection rules, and deduplication |
| `tests/test_parser.py` | Sandbox and file persistence |
| `tests/test_reel_import.py` | Agent repair, reuse, and command behavior |

### Task 1: Define the output contract and host checks

**Files:** Create `reels.py` and `tests/test_reels.py`.

**Interfaces:**

- `Reel`: required `url: str` and required `author_username: str | None`.
- `check_output(raw: object) -> list[Reel]`: check returned objects, apply collection rules, and deduplicate reels.
- Use strict Pydantic fields and forbid extra output fields.

- [x] Write `test_reel_output` with actual values. Assert the exact URL and `theanomalyvault` username.
- [x] Write `test_unknown_author`. Assert the same URL remains and `author_username` is null.
- [x] Add cases for missing fields, extra fields, wrong types, empty usernames, and malformed or non-Instagram URLs.
- [x] Add cases for `/p/` exclusions, an empty collection, deduplication, and conflicting authors.
- [x] Run the focused tests before implementation. Observed the expected missing `reels.py` import failure.
- [x] Implement `Reel` and `check_output` in `reels.py`.
- [x] Repeat the focused tests. All 15 tests pass with the project virtual environment.

**Done:** The host checks returned values, excludes non-reel posts, and deduplicates results without an LLM or sandbox.

**Execution notes:** Task 1 uses the existing checkout and this plan for progress, consistent with the requested minimal scope.
The baseline suite exposed nine failures because `Agent.run()` returned the literal `done!` instead of the final response content.
Restoring that return value made all 12 baseline tests pass before the new module was implemented.
URL normalization merges shared links with different tracking parameters while preserving shortcode case.
Task 1 is complete. Subsequent tasks record their own implementation progress.

**Verification:** `rtk proxy .venv/bin/python -m unittest discover -s tests -v` passes all 27 tests.
`rtk proxy .venv/bin/ruff check .` passes. Ruff formatting and `git diff --check` also pass for the changes.

### Task 2: Run and store Python parsers

**Files:** Create `parser.py` and `tests/test_parser.py`. Modify `pyproject.toml`, `uv.lock`, and `.gitignore` through normal dependency tooling.

**Interfaces:**

- `async run_parser(code: str, data: object) -> object`: run the source and call `parse(data)` inside Monty.
- `read_parser(parser_dir: Path) -> str`: read `latest.py`.
- `save_parser(parser_dir: Path, code: str) -> None`: atomically replace `latest.py` and preserve `previous.py`.
- Use `.reels-parser/` as the default ignored directory. Tool callers cannot choose arbitrary write paths.
- Call `save_parser` only after sandbox execution and host checks succeed.

- [x] Fetch current Monty installation and execution documentation before the dependency change.
- [x] Write `test_run_parser` with source `def parse(data): return data`. Assert the result equals the input.
- [x] Add cases for a Python exception, an infinite loop, and a host file read attempt.
- [x] Add persistence cases for first save, replacement, and preservation of the previous source.
- [x] Run the focused tests before implementation. Observed the expected missing `parser.py` import failure.
- [x] Add `pydantic-monty` with `uv add`. Let uv maintain the lockfile.
- [x] Implement Monty execution with a 2-second execution budget, a 32 MiB memory budget, and a 5-second host timeout.
- [x] Implement file persistence with standard-library file operations. Expose no host capabilities to Monty.
- [x] Repeat the focused tests. All 16 tests pass with the project virtual environment.

**Done:** Python extraction runs in the sandbox, and successful source can persist across imports.

**Execution notes:** Each call creates a fresh async Monty pool with one worker.
The host deadline wraps the entire operation, including sleep and sandbox setup.
Parser print output is discarded. Native syntax and runtime exceptions propagate to the caller.
Storage writes UTF-8 source through temporary files and atomic replacements. Failed writes clean up temporary files.
An unsuccessful latest replacement preserves the working latest file and its backup.
The caller remains responsible for execution and output checks before saving. Task 3 connects that sequence.

**Verification:** All 43 tests pass, including real sandbox resource limits, denied host access, and storage failure cases.
Both complete JSON examples passed a sandbox round-trip within the configured limits.
Ruff lint, formatting, `git diff --check`, and the cache ignore rule pass.
Task 2 is complete. Subsequent tasks track agent repair and CLI integration.

### Task 3: Connect parser reuse and repair to the existing agent

**Files:** Create `reel_tools.py` and `tests/test_reel_import.py`. Modify `agent.py` and its existing tests.

**Interfaces:**

- `async try_saved_parser(data: object, parser_dir: Path) -> list[Reel]`: run saved source and apply `check_output`.
- `async repair_parser(data: object, llm: LLM, parser_dir: Path, previous_error: str) -> list[Reel]`.
- `inspect_reels_json` tool arguments: `path: list[str | int]`, `offset: int = 0`, `limit: int = 3`.
- `try_reels_parser` tool arguments: `code: str`. Run the candidate, apply host checks, and save successful source.
- Inspection returns the node type, collection length, and a paginated JSON sample capped at 12,000 characters.
- The agent can request another path or array slice.
- Candidate tools share import state through their instances. Reuse `Agent.run` and its existing tool error feedback.
- `Agent.run(prompt)` ends when the model returns an `AgentResponse` with decision STOP.
- Repair uses a fresh agent. Its prompt requests STOP after acceptance or exhausted candidate attempts.
- The candidate tool refuses a fourth execution. Existing consecutive-response limits bound repeated tool responses.

- [x] Write `test_repair_then_reuse` with the existing scripted-LLM pattern. Assert successful repair saves source and reuse makes no model call.
- [x] Add cases for missing source, failed source, early agent STOP, and three failed candidate executions.
- [x] Add compact fixtures from both supplied formats. Assert the exact URL-author pairs supplied in the conversation.
- [x] Reorder `label_values` and include a caption reel URL. Assert that the saved reel and its owner remain paired.
- [x] Add a missing-author fixture. Assert that the reel remains with a null author.
- [x] Run regression tests before implementation and before changing completion behavior.
- [x] Implement the two tools and the reuse and repair functions.
- [x] Limit candidate executions to three per import. Use the harness limit of twelve consecutive tool-call responses.
- [x] Return structured failure details to the model. Preserve the saved source after failed candidates.
- [x] If the agent stops without an accepted candidate, raise an import error. Never use its prose as parsed output.
- [x] Repeat the focused tests. All 21 import tests pass, including explicit model STOP responses.

**Done:** The agent learns the mapping when necessary, and compatible imports reuse saved source.

**Execution notes:** The initial prompt includes a bounded JSON preview, the previous source, and the previous error.
After review, the user chose model-controlled completion through `AgentResponse`.
The host callback and parser stop predicate were removed. The model reads the tool result before choosing STOP.
The tool retains its three-execution limit, including within a batch of candidate submissions.
A successful revision replaces the accepted parser before STOP. A failed revision preserves the last accepted parser.
The host returns validated parser results after STOP and rejects premature success claims.
An empty accepted list remains a successful result. Failed candidates never reach storage.
All new functions and methods use `@beartype`. Existing decorators remain intact.
Imports follow the user's move of tool modules into `src/reels_ripper_agent/tools/`.
The existing parser and output modules received blank-line formatting corrections only.

**Verification:** All 64 tests pass after the completion change. Ruff lint, formatting across `src` and `tests`, and `git diff --check` pass.
Complete-file smoke runs produced 362 reels from the first export and 54 from the second export.
Both expected URL-author pairs passed, cached reuse made no additional model call, and schema repair preserved the previous source.
Complete-file smoke runs also consumed explicit model STOP responses after each accepted parser.
Original Task 3 checks used scripted LLM responses and real Monty execution. Later live checks appear in the provider regression section.
Task 3 is complete. Task 4 records CLI integration and final verification.

### Task 4: Expose the import command and exercise the full flow

**Files:** Modify `__init__.py`, `agent.py`, `README.md`, and `tests/test_reel_import.py`.

**Interfaces:**

- `uv run reels-ripper-agent --reels-file PATH`: import a JSON file and print normalized reels as JSON.
- Existing positional prompts retain their current behavior.
- Try the saved parser before constructing `OpenRouterLLM`. Compatible imports need no model credentials.
- Send progress and diagnostics to stderr. Print validated results to stdout.

- [x] Write cached command cases with no credentials and a model factory that rejects construction.
- [x] Add command cases for generation, drift repair, and exhausted candidates. Assert failures preserve saved source and return a nonzero exit.
- [x] Run command tests before implementation. Observed missing file mode, polluted stdout, and unnecessary model construction.
- [x] Add the file argument with standard-library argparse and connect the import functions.
- [x] Route existing agent progress output to stderr so stdout remains usable JSON.
- [x] Add the invocation and cache location to README.md.
- [x] Run the full suite and Ruff checks with the project virtual environment. All 74 tests pass.
- [x] Run scripted end-to-end imports against both complete JSON examples. Assert the expected example pairs, reel-only URLs, and deduplication.
- [x] Run the installed command twice per export with no API key and dotenv loading disabled. Cached results match exactly.

**Done:** The command supports first import, compatible reuse, schema drift, and candidate execution limits.

**Execution notes:** `_main_reels(path)` reads the input before it attempts cached parsing.
Only a missing or incompatible parser causes model-client construction. The client closes after repair success or failure.
Standard argparse provides offline help and rejects a file argument combined with a positional prompt.
The existing prompt and default weather modes still print their final answer to stdout.
All progress and model commentary go to stderr. Command errors return a nonzero exit code without a stdout result.
Remaining imports follow the user's tool-base rename to `tools/base.py`.

**Verification:** All 74 tests pass. Ruff lint, formatting, and `git diff --check` pass.
Both complete exports pass scripted generation or repair through the command entry point: 362 and 54 reels.
The installed console script passes repeated cached imports, offline help, and a missing-file failure without model credentials.
Original generation tests used scripted model replies with real Monty execution. Later live checks appear in the provider regression section.
Independent final review found no Critical, Important, or Minor issues and independently passed all 74 tests.
The review accepted the user's explicit choices to trust extraction accuracy and use model-controlled STOP.
The original review did not establish live provider reliability. Later live checks appear in the provider regression section.
All four tasks are complete. Working-tree changes remain available for the user's own commit workflow.

## Provider Tool-Calling Regression

The first live user run returned text claiming that the parser tool was unavailable.
The request included both parser tools, but also forced `response_format: {"type": "json_object"}`.
Live synthetic reproduction with MiniMax M3.1 Flash on DigitalOcean produced only JSON progress messages and no native tool calls.
Removing that output constraint on the same provider enabled inspection, parser submission, and a structured STOP response.

The adapter now enables provider JSON-only mode only when no tools are supplied.
Schema instructions and host Pydantic validation remain active for text responses during tool use.
This fix restores the documented workflow and requires no new user configuration.

A regression case exercises the real OpenRouter adapter through the CLI, agent, Monty, and persistence with a mock HTTP transport.
The case reproduced the missing-tool failure before the fix. It passes after the fix.
A separate case preserves JSON-only mode for requests without tools.

All 76 tests pass. Ruff lint, formatting, and `git diff --check` pass.
The actual fixed console script passed live generation and schema repair on two synthetic formats with invented links and usernames.
Both outputs matched expected values. Model STOP and credential-free cached reuse passed for each format.
Automatic approval review blocked the proposed private-export upload before execution. No private export was uploaded during live verification.

## Empty Output and Ignored Revisions

The next live run returned an empty list for an export containing 362 reels.
Local reproduction confirmed that the cached parser read a top-level `url` field instead of the nested saved-post permalink.
It silently skipped all records. The output contract accepted the resulting empty list.
The candidate tool then ignored subsequent source submissions once any candidate had succeeded, so the model could not correct that result.

Each submitted candidate now executes within the existing three-attempt budget, including revisions after acceptance.
A successful revision replaces the saved source and result. A failed revision leaves the last accepted source and result intact.
The prompt requires critical permalink fields and asks the model to review empty counts against the inspected input before STOP.
It also leaves URL filtering, normalization, and deduplication to the host.
The host still trusts extraction semantics and accepts legitimate empty collections.

Regression tests reproduced the ignored correction and misleading acceptance feedback before the fix.
All 78 tests now pass, including revision replacement, failed-revision preservation, and the candidate limit across successful revisions.
Ruff lint, formatting, and `git diff --check` pass.

The configured model generated a replacement from invented export records in a temporary cache.
The replacement passed local verification against all 362 URL-author pairs in the first private export before promotion through `save_parser`.
The prior parser remains in `previous.py`. No generated source was manually patched.
The actual `uv run reels-ripper-agent --reels-file json_examples/saved_posts_1.json` command returns 362 reels with model credentials removed and networking disabled.
No private export was uploaded during recovery.

## Execution Order

Review the contract in Task 1 first. Implement and demonstrate one task before the next task starts.
The first implementation action is a baseline test run. Record existing failures before edits.
Keep generated parsers inside the ignored cache. Do not add user exports to commits without a separate request.
