.PHONY: install run test frontend-build

install:
	python -m pip install -e './backend[dev]'
	cd frontend && npm install

run:
	cd backend && python -m uvicorn app.main:app --reload --port 8000

test:
	cd backend && python -m pytest

frontend-build:
	cd frontend && npm run build

