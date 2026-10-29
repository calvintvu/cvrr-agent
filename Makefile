.PHONY: run

# Treat goals after run as the prompt, and pass it through the environment safely.
ifeq ($(firstword $(MAKECMDGOALS)),run)
export RUN_PROMPT := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
%:
	@:
endif

run:
	uv run reels-ripper-agent $${RUN_PROMPT:+"$$RUN_PROMPT"}
