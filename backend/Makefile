.PHONY: install test test-verbose

# Create the virtual environment and install the dependencies
install:
	python3 -m venv .venv
	.venv/bin/pip install pydantic pytest langgraph

# Run all tests, or only one file: make test T=incoming_report
test:
ifdef T
	.venv/bin/pytest -q tests/test_$(T).py
else
	.venv/bin/pytest -q
endif

# Same as test, but prints one line per test
test-verbose:
ifdef T
	.venv/bin/pytest -v tests/test_$(T).py
else
	.venv/bin/pytest -v
endif
