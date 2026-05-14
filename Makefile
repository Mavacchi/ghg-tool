# GHG Tool — Developer Makefile
#
# Prerequisites: Python 3.11, Docker + Docker Compose, make
#
# Quick start:
#   make install   — install all dev dependencies + pre-commit hooks
#   make db-up     — start PostgreSQL container (detached)
#   make migrate   — apply Alembic migrations to head
#   make lint      — run ruff + mypy
#   make test      — run unit tests with coverage gate
#   make etl       — placeholder ETL run (wave 3)
#   make db-down   — stop + remove containers and volumes

.PHONY: all install lint test test-unit test-integration \
        db-up db-down migrate etl py-compile \
        seed-user seed-data \
        pre-commit-install help

# ---------------------------------------------------------------------------
# Variables (override via: make test PYTEST_ARGS="-k test_foo")
# ---------------------------------------------------------------------------
PYTHON      := python3.11
PYTEST      := $(PYTHON) -m pytest
RUFF        := $(PYTHON) -m ruff
MYPY        := $(PYTHON) -m mypy
ALEMBIC     := $(PYTHON) -m alembic
COVERAGE    := $(PYTHON) -m coverage

SRC_DIR     := src/ghg_tool
TEST_DIR    := tests
UNIT_DIR    := $(TEST_DIR)/unit
INTEG_DIR   := $(TEST_DIR)/integration

PYTEST_ARGS ?=

# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------
all: lint test

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
install:
	@echo "==> Installing dev dependencies..."
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"
	@echo "==> Installing pre-commit hooks..."
	$(PYTHON) -m pre_commit install
	@echo "==> Done. Run 'make db-up migrate' to start the database."

# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------
lint:
	@echo "==> Running ruff..."
	$(RUFF) check $(SRC_DIR) $(TEST_DIR)
	@echo "==> Running mypy (strict)..."
	$(MYPY) $(SRC_DIR)
	@echo "==> Lint passed."

# ---------------------------------------------------------------------------
# Syntax check (fast — no imports)
# ---------------------------------------------------------------------------
py-compile:
	@echo "==> Compiling all Python files..."
	find $(SRC_DIR) $(TEST_DIR) alembic/versions -name "*.py" \
	    -exec $(PYTHON) -m py_compile {} +
	@echo "==> All files compile cleanly."

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test: test-unit

test-unit:
	@echo "==> Running unit tests with coverage..."
	$(PYTEST) $(UNIT_DIR) \
	    -x \
	    --tb=short \
	    --strict-markers \
	    --cov=$(SRC_DIR) \
	    --cov-report=term-missing \
	    --cov-fail-under=85 \
	    $(PYTEST_ARGS)

test-integration: ## Run integration tests against the docker-compose test stack (port 5433)
	@echo "==> Starting test PostgreSQL on host port 5433..."
	docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db-test
	@echo "==> Waiting for test DB to be ready..."
	@until docker exec ghg_db_test pg_isready -U ghg_test -d ghg_tool_test > /dev/null 2>&1; do \
	    printf '.'; sleep 1; \
	done
	@echo ""
	@echo "==> Applying Alembic migrations to test DB..."
	SQLALCHEMY_URL="postgresql+psycopg://ghg_test:ghg_test_password@localhost:5433/ghg_tool_test" \
	    $(ALEMBIC) upgrade head
	@echo "==> Running integration tests..."
	SQLALCHEMY_URL="postgresql+psycopg://ghg_test:ghg_test_password@localhost:5433/ghg_tool_test" \
	SQLALCHEMY_ASYNC_URL="postgresql+asyncpg://ghg_test:ghg_test_password@localhost:5433/ghg_tool_test" \
	DATABASE_URL="postgresql+asyncpg://ghg_test:ghg_test_password@localhost:5433/ghg_tool_test" \
	JWT_SECRET_KEY="test-secret-only-for-local-min-32-characters" \
	ENV="test" \
	    $(PYTEST) $(INTEG_DIR) \
	        -v -m integration \
	        --tb=short \
	        --strict-markers \
	        $(PYTEST_ARGS)

test-integration-down: ## Stop and remove the integration test stack + volume
	@echo "==> Tearing down integration test stack..."
	docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
	@echo "==> Done."

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
db-up:
	@echo "==> Starting PostgreSQL container..."
	docker compose up db -d
	@echo "==> Waiting for PostgreSQL to be healthy..."
	@until docker compose exec db pg_isready -U ghg_app -d ghg_tool 2>/dev/null; do \
	    printf '.'; sleep 1; \
	done
	@echo ""
	@echo "==> PostgreSQL is ready at localhost:5432 (database: ghg_tool)"

db-down:
	@echo "==> Stopping and removing containers + volumes..."
	docker compose down -v
	@echo "==> Done."

migrate:
	@echo "==> Applying Alembic migrations to head..."
	$(ALEMBIC) upgrade head
	@echo "==> Migration complete."

migrate-status:
	@echo "==> Current migration status:"
	$(ALEMBIC) current
	$(ALEMBIC) heads

migrate-rollback:
	@echo "==> Rolling back one migration step..."
	$(ALEMBIC) downgrade -1

# ---------------------------------------------------------------------------
# ETL (wave 3 placeholder)
# ---------------------------------------------------------------------------
etl:
	@echo "==> ETL pipeline — wave 3 placeholder."
	@echo "==> Usage: SCOPE1=data/raw/scope1.csv SCOPE2=data/raw/scope2.csv"
	@echo "==>         SCOPE3=data/raw/scope3.csv make etl"
	@echo "Wave 3 will implement: $(PYTHON) -m ghg_tool.etl.orchestrator run ..."

# ---------------------------------------------------------------------------
# Operational seed scripts (run inside the `app` container)
# ---------------------------------------------------------------------------
# Usage:
#   USERNAME=marco EMAIL=marco@example.com ROLE=esg_manager make seed-user
#   make seed-data
#
# Variables (override on command line):
#   USERNAME  ROLE  EMAIL  TENANT_CODE  (seed-user)
#   DATA_DIR  TENANT_CODE                (seed-data)
USERNAME    ?= admin
EMAIL       ?= admin@example.com
ROLE        ?= esg_manager
TENANT_CODE ?= CERAMIC_TILE_CO
DATA_DIR    ?= data/raw

seed-user:
	@echo "==> Creating user '$(USERNAME)' (role=$(ROLE), tenant=$(TENANT_CODE))..."
	$(PYTHON) -m scripts.create_user \
		--username "$(USERNAME)" \
		--email    "$(EMAIL)" \
		--role     "$(ROLE)" \
		--tenant-code "$(TENANT_CODE)"

seed-data:
	@echo "==> Seeding raw.scope*_ingestions from $(DATA_DIR)/ ..."
	$(PYTHON) -m scripts.seed_demo_data \
		--data-dir    "$(DATA_DIR)" \
		--tenant-code "$(TENANT_CODE)"

# ---------------------------------------------------------------------------
# Pre-commit
# ---------------------------------------------------------------------------
pre-commit-install:
	$(PYTHON) -m pre_commit install

pre-commit-run:
	$(PYTHON) -m pre_commit run --all-files

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "GHG Tool — available make targets:"
	@echo ""
	@echo "  install            Install dev deps + pre-commit hooks"
	@echo "  lint               Run ruff + mypy"
	@echo "  py-compile         Syntax-check all Python files"
	@echo "  test               Run unit tests (alias: test-unit)"
	@echo "  test-unit          Run unit tests with coverage gate"
	@echo "  test-integration   Run integration tests against docker-compose test stack"
	@echo "  test-integration-down  Stop + remove the integration test stack"
	@echo "  db-up              Start PostgreSQL in Docker (detached)"
	@echo "  db-down            Stop containers + remove volumes"
	@echo "  migrate            Apply Alembic migrations to head"
	@echo "  migrate-status     Show current Alembic revision"
	@echo "  migrate-rollback   Downgrade one step"
	@echo "  etl                ETL pipeline (wave 3 placeholder)"
	@echo "  seed-user          Create a user (USERNAME=... EMAIL=... ROLE=...)"
	@echo "  seed-data          Ingest data/raw/ CSVs into raw.scope*_ingestions"
	@echo "  pre-commit-run     Run all pre-commit hooks"
	@echo ""
	@echo "Variables (override on command line):"
	@echo "  PYTEST_ARGS        Extra arguments passed to pytest"
