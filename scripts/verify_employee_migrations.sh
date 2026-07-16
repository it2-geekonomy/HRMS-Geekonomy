#!/bin/bash
# Run on the SERVER (where Docker runs) to verify employee migrations exist.
# Usage: ./scripts/verify_employee_migrations.sh

set -e
echo "=== 1. Employee migrations in current directory (host) ==="
ls -la employee/migrations/*.py 2>/dev/null || echo "No migration files found on host - run: git pull"

echo ""
echo "=== 2. Employee migrations inside container ==="
docker exec horilla-hrms ls -la /app/employee/migrations/*.py 2>/dev/null || echo "No migration files in container - rebuild image: docker-compose -f docker-compose.prod.yaml up --build -d"

echo ""
echo "=== 3. Django migration status for employee ==="
docker exec horilla-hrms python manage.py showmigrations employee 2>/dev/null || true
