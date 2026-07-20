.PHONY: install infra-install run test frontend-build migrate r2-accept demo-accept-offline demo-accept

install:
	python -m pip install -e './backend[dev]'
	cd frontend && npm install

infra-install:
	python -m pip install -e './backend[dev,infra]'

run:
	cd backend && python -m uvicorn app.main:app --reload --port 8000

test:
	cd backend && python -m pytest

frontend-build:
	cd frontend && npm run build

migrate:
	cd backend && python -m alembic upgrade head

r2-accept:
	cd backend && python -m app.cli.r2_acceptance

demo-accept-offline:
	cd backend && python -m app.cli.demo_acceptance

demo-accept:
	cd backend && python -m app.cli.demo_acceptance --with-infrastructure
