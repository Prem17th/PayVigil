PYTHON ?= .venv/bin/python

.PHONY: help install lint check check-fast frontend release-plan

help:
	@printf '%s\n' \
	  'install       Install into an existing .venv and use the frontend lockfile' \
	  'lint          Check Python formatting and basic correctness' \
	  'check         Full local checks; requires disposable LOCAL_TEST_ADMIN_URL' \
	  'check-fast    Checks without PostgreSQL integration; not a release check' \
	  'frontend      Frontend boundary checks and production build' \
	  'release-plan  Offline Render configuration plan; creates no resources'

install:
	$(PYTHON) -m pip install -r backend/requirements-dev.txt
	$(PYTHON) -m pip check
	cd frontend && npm ci

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

check: lint
	$(PYTHON) scripts/check.py --postgres

check-fast: lint
	$(PYTHON) scripts/check.py

frontend:
	cd frontend && npm test && npm run build

release-plan:
	$(PYTHON) scripts/render_release.py plan
