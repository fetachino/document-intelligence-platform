$ErrorActionPreference = 'Stop'

Write-Host 'Starting verification script for Milestone 1...'
$root = Get-Location

# 1) Ensure Poetry is installed (do not auto-install)
Write-Host '1) Ensure Poetry is installed'
if (-not (Get-Command 'poetry' -ErrorAction SilentlyContinue)) {
    Write-Host 'Poetry is not installed. Please install Poetry and re-run verification. See https://python-poetry.org/docs/#installation'
    Exit 1
}

# 2) Install backend dependencies with Poetry (including dev)
Write-Host '2) Install backend dependencies with Poetry (including dev)'
poetry config virtualenvs.create false
poetry install --with dev --no-interaction --no-ansi
if ($LASTEXITCODE -ne 0) { throw 'poetry install failed' }

# 3) Ruff format/lint check
Write-Host '3) Ruff format/lint check'
poetry run ruff check .
if ($LASTEXITCODE -ne 0) { throw 'ruff check failed' }

# 4) mypy type check (backend)
Write-Host '4) mypy type check (backend)'
poetry run mypy backend
if ($LASTEXITCODE -ne 0) { throw 'mypy failed' }

# 5) Start docker-compose DB (pgvector)
Write-Host '5) Start docker-compose DB (pgvector)'

# Detect docker compose command
$composeSubcommand = $null
if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
    try {
        docker compose version > $null 2>&1
        $composeSubcommand = 'compose'
    } catch {
        if (-not (Get-Command 'docker-compose' -ErrorAction SilentlyContinue)) {
            Write-Host 'Neither "docker compose" nor "docker-compose" found. Please install Docker and Docker Compose.'
            Exit 1
        }
    }
} elseif (-not (Get-Command 'docker-compose' -ErrorAction SilentlyContinue)) {
    Write-Host 'Docker is not installed. Please install Docker and Docker Compose.'
    Exit 1
}

if ($composeSubcommand -eq 'compose') { Write-Host 'Using: docker compose' } else { Write-Host 'Using: docker-compose' }

# start db
if ($composeSubcommand -eq 'compose') {
    docker compose up -d db
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }
} else {
    docker-compose up -d db
    if ($LASTEXITCODE -ne 0) { throw 'docker-compose up failed' }
}

# 6) Wait for Postgres readiness (pg_isready)
Write-Host '6) Wait for Postgres readiness (pg_isready)'
$timeout = 120; $t = 0; while ($t -lt $timeout) {
    $attempt = $t/2 + 1
    Write-Host "Checking Postgres readiness (attempt $attempt/$([int]($timeout/2)))..."

    # Run pg_isready via docker compose and capture both output and exit code
    if ($composeSubcommand -eq 'compose') {
        $output = & docker compose exec -T db pg_isready -U docuser -d docdb 2>&1
    } else {
        $output = & docker-compose exec -T db pg_isready -U docuser -d docdb 2>&1
    }
    $exit = $LASTEXITCODE
    Write-Host "pg_isready exit code: $exit"
    Write-Host "pg_isready output: $output"

    if ($exit -eq 0) {
        Write-Host 'Postgres is ready (pg_isready returned 0)'
        break
    }

    # If pg_isready did not report ready, check container health via docker inspect
    try {
        if ($composeSubcommand -eq 'compose') {
            $cid = (docker compose ps -q db) -join ''
        } else {
            $cid = (docker-compose ps -q db) -join ''
        }
        if ($cid) {
            $health = (& docker inspect --format '{{.State.Health.Status}}' $cid 2>&1) -join ''
            Write-Host "Container health status: $health"
            if ($health -eq 'healthy') {
                Write-Host 'Container reports healthy — assuming Postgres is ready'
                break
            }
        } else {
            Write-Host 'Could not determine container id for db'
        }
    } catch {
        Write-Host 'Error checking container health — will retry'
    }

    Start-Sleep -Seconds 2; $t += 2
}
if ($t -ge $timeout) { throw 'Postgres did not become ready in time' }

# 7) Run Alembic migrations
Write-Host '7) Run Alembic migrations'
$env:DATABASE_URL = 'postgresql+asyncpg://docuser:docpass@localhost:5432/docdb'
poetry run alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }

# 8) Run backend tests
Write-Host '8) Run backend tests'
poetry run pytest backend/tests -q --maxfail=1
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }

# 9) Frontend: install and run checks
Write-Host '9) Frontend: install and run checks'
Push-Location frontend

# Find npm command on Windows (npm or npm.cmd) or Unix (npm)
$npmCmd = $null
if (Get-Command 'npm' -ErrorAction SilentlyContinue) {
    $npmCmd = 'npm'
} elseif (Get-Command 'npm.cmd' -ErrorAction SilentlyContinue) {
    $npmCmd = 'npm.cmd'
} else {
    Write-Host 'npm is not installed or not on PATH. Please install Node.js LTS and ensure npm is on PATH, then rerun verification.'
    Pop-Location
    Exit 1
}

Write-Host "Using npm command: $npmCmd"

# Run npm commands via the detected command
& $npmCmd ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }

& $npmCmd run lint
if ($LASTEXITCODE -ne 0) { throw 'frontend lint failed' }

& $npmCmd run typecheck
if ($LASTEXITCODE -ne 0) { throw 'frontend typecheck failed' }

& $npmCmd run test -- --run --coverage
if ($LASTEXITCODE -ne 0) { throw 'frontend tests failed' }

& $npmCmd run build
if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
Pop-Location

# 10) Build Docker images
Write-Host '10) Build Docker images'

docker build -f ./backend/Dockerfile -t dip-backend .
if ($LASTEXITCODE -ne 0) { throw 'backend docker build failed' }

docker build -f ./frontend/Dockerfile -t dip-frontend .
if ($LASTEXITCODE -ne 0) { throw 'frontend docker build failed' }

Write-Host 'Verification complete.'
