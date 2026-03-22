PYTHON ?= python3
TEST_BATCH_ARGS ?=
WORKER_REMOTE_ENV ?= deploy/env/worker.remote.env

.PHONY: tree api-run scheduler-run worker-run compose-local-config compose-local-up compose-local-down \
	compose-remote-worker-config compose-remote-worker-up compose-remote-worker-down \
	compose-remote-worker-2gpu-config compose-remote-worker-2gpu-up compose-remote-worker-2gpu-down \
	env-init env-init-force test-batch

tree:
	find . -maxdepth 3 | sort

api-run:
	PYTHONPATH=packages/common/src:packages/gvhmr_runner/src:services/api/src \
	$(PYTHON) -m gvhmr_batch_api.main

scheduler-run:
	PYTHONPATH=packages/common/src:services/scheduler/src \
	$(PYTHON) -m gvhmr_batch_scheduler.main

worker-run:
	PYTHONPATH=packages/common/src:packages/gvhmr_runner/src:services/worker/src \
	$(PYTHON) -m gvhmr_batch_worker.main

env-init:
	bash deploy/scripts/init_env.sh

env-init-force:
	FORCE=1 bash deploy/scripts/init_env.sh

compose-local-config:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml config

compose-local-up:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml up --build

compose-local-down:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml down

compose-remote-worker-config:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.yml config

compose-remote-worker-up:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.yml up --build -d

compose-remote-worker-down:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.yml down

compose-remote-worker-2gpu-config:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.2gpu.yml config

compose-remote-worker-2gpu-up:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.2gpu.yml up --build -d

compose-remote-worker-2gpu-down:
	docker compose --env-file $(WORKER_REMOTE_ENV) -f deploy/compose.worker.remote.2gpu.yml down

test-batch:
	$(PYTHON) test/run_batch_test.py $(TEST_BATCH_ARGS)
