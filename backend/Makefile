.PHONY: install test test-verbose test-integration graph run

# Create the virtual environment and install the dependencies
install:
	python3 -m venv .venv
	.venv/bin/pip install pydantic pytest langgraph gliner2 torch transformers huggingface_hub supabase python-dotenv pillow pillow-heif opencv-python-headless rapidocr onnxruntime fastapi uvicorn

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

# Print the privacy graph as a Mermaid diagram (generated from the code)
graph:
	PYTHONPATH=. .venv/bin/python scripts/draw_graph.py

# Tests against the real Supabase project (needs backend/.env)
test-integration:
	.venv/bin/pytest -v -m integration

# Start the API on this machine (http://127.0.0.1:8000, try /health). Needs backend/.env
run:
	PYTHONPATH=. .venv/bin/uvicorn --factory api.main:create_app --port 8000
