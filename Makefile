.PHONY: run

run:
	uv run reels-ripper-agent

format:
	uv run ruff format .

check:
	uv run ruff check .
