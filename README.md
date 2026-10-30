# Reels Ripper Agent

Import Instagram reel links and author usernames from JSON exports.
The agent generates a Python parser when no saved parser exists or parsing fails.
Monty runs the parser with execution and memory limits.

```bash
uv run reels-ripper-agent --reels-file /path/to/instagram-export.json
```

The command prints one JSON array to stdout. Progress and errors go to stderr.
Unknown authors appear as `"author_username": null`. Ordinary posts are excluded, and duplicate reel links are merged.
A failed import returns a nonzero exit code.

Set `OPENROUTER_API_KEY` in the environment or a `.env` file for parser generation and repair.
See [.env.example](.env.example). `OPENROUTER_MODEL` defaults to `openrouter/free`.
Imports with a compatible saved parser need no model credentials or model calls.

The cache lives in `.reels-parser/` under the current working directory.
`latest.py` contains the current parser. `previous.py` preserves its predecessor.
The agent can try three candidates during repair. Failed candidates do not replace the saved parser.

Positional text runs the existing agent:

```bash
uv run reels-ripper-agent "What's the weather in Tokyo?"
```

Without arguments, the agent uses that weather prompt.
Use `--reels-file` separately from positional prompts.

Run the checks with:

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
```
