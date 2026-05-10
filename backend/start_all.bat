@echo off

echo Starting Redis (Docker)...
docker start f-ai-redis
echo Starting migrations...
start cmd /k alembic upgrade head

echo Starting Celery...
start cmd /k celery -A app.workers.celery_app worker ^
  --pool=solo ^
  --loglevel=info ^
  --queues=critical,default,celery

echo Starting FastAPI...
start cmd /k uvicorn app.main:app --reload

echo All services started!