python reels thingy agent

Set `CVRR_DATA_DIR` in your environment or `.env` to choose where the agent stores
`.downloads/`, `.parsers/`, `.processed/`, and `reels.db`:

```dotenv
CVRR_DATA_DIR=~/cvrr-data
```

When unset or empty, it defaults to the current directory (the repository root
when run from this repo). Relative paths are relative to the current directory.
Missing directories are created as needed. Environment variables take precedence
over `.env`. Existing data is not moved automatically.
