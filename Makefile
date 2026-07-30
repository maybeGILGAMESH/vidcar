SHELL := /usr/bin/env bash

.PHONY: help bootstrap validate preflight up down smoke test

help:
	@printf '%s\n' \
	  'bootstrap  Check prerequisites; install nothing' \
	  'validate   Validate the stage-1 repository scaffold' \
	  'preflight  Check GPU/Docker/models readiness' \
	  'up         Start Compose stack (blocked without Docker)' \
	  'down       Stop Compose stack (blocked without Docker)' \
	  'smoke      Local GPU smoke + approved manifest check' \
	  'test       Run unit/gpu/recovery/load pytest suite'

bootstrap:
	@./scripts/bootstrap.sh

validate:
	@./scripts/validate.sh

preflight:
	@./scripts/preflight.sh

up:
	@./scripts/up.sh

down:
	@./scripts/down.sh

smoke:
	@./scripts/smoke.sh

test:
	@./scripts/test.sh
