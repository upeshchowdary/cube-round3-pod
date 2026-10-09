.PHONY: setup test e2e run case serve ui up health examples expected cases

# Windows (Git Bash / MSYS make) has python and .venv/Scripts; macOS/Linux have python3 and .venv/bin.
# No make at all? Every target below has a twin in `python scripts/dev.py <target>`.
ifeq ($(OS),Windows_NT)
PYTHON ?= python
BIN := .venv/Scripts
else
PYTHON ?= python3
BIN := .venv/bin
endif

setup:            ## create .venv and install dependencies
	$(PYTHON) -m venv .venv && $(BIN)/python -m pip install -r requirements.txt
	@test -f .env || cp .env.example .env
	$(BIN)/python scripts/fetch_photos.py

test:             ## all tests: contracts, hand-offs, workflow state, UNCERTAIN, failures, overrides, e2e, HTTP, examples
	$(BIN)/python -m pytest

e2e:              ## just the end-to-end tests
	$(BIN)/python -m pytest tests/e2e

run: export LOG_LEVEL = WARNING
run:              ## run every sample workflow afresh (old state -> out/_previous/); state -> out/workflows, evidence -> out/evidence
	$(BIN)/python -m orchestration.run --all --fresh
	@if [ -f data/input/UNIT-C26RM-001/pack/open_box.jpg ]; then RETURNS_LIVE_FALLBACK=0 $(BIN)/python -m orchestration.run --all --cases data/input/returns_photo_cases.json; else echo "real-photo units skipped: run $(BIN)/python scripts/fetch_photos.py"; fi

case:             ## one workflow, full JSON:  make case UNIT=UNIT-0014 ORG=org_demo_alpha
	@$(BIN)/python -m orchestration.run --unit $(UNIT) --org $(ORG)

serve:            ## orchestrator API on :8100  (POST /workflows, GET /workflows/{id}, GET /health)
	$(BIN)/python -m uvicorn orchestration.api:app --port 8100

ui:               ## the UI on :5173 (needs `cd ui && npm ci` once, and the API on :8100)
	cd ui && npm run dev

up:               ## API + UI together; Ctrl+C stops both
	$(BIN)/python scripts/dev.py up

health:           ## health of the orchestrator and every agent
	curl -s localhost:8100/health | $(BIN)/python -m json.tool

cases:            ## rebuild data/sample/cases.json from the sample CSVs
	$(BIN)/python scripts/build_sample_cases.py

expected:         ## rebuild data/expected/ (golden outcomes for the organiser STUBS + standard flow)
	$(BIN)/python scripts/build_expected.py

examples:         ## regenerate examples/ from real runs of the stubs
	$(BIN)/python scripts/make_examples.py
