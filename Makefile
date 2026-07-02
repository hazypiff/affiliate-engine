PY := .venv/bin
export PATH := $(PY):$(PATH)

.PHONY: init-db test e2e verify demo-real lint

init-db:
	$(PY)/engine init-db

lint:
	$(PY)/ruff check engine tests

test:
	$(PY)/pytest tests/unit tests/integration

e2e:
	$(PY)/python tests/e2e/smoke.py

verify: lint test e2e
	@echo "VERIFY PASSED"

demo-real:
	bash scripts/demo_real_llm.sh
