.PHONY: install lint typecheck test run-backend run-frontend

install:
	pip install -r backend/requirements-dev.txt
	pip install -r frontend/requirements.txt

lint:
	ruff check backend/

typecheck:
	mypy backend/app/

test:
	pytest backend/tests/ -v --cov=backend/app --cov-report=term-missing

run-backend:
	cd backend && uvicorn app.main:app --reload

run-frontend:
	streamlit run frontend/app.py
