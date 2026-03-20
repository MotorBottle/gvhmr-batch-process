PYTHON ?= python3
TEST_BATCH_ARGS ?=

.PHONY: tree api-run scheduler-run worker-run compose-local-config compose-local-up compose-local-down test-batch

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

compose-local-config:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml config

compose-local-up:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml up --build

compose-local-down:
	docker compose -f deploy/compose.base.yml -f deploy/compose.control-plane.yml -f deploy/compose.worker.yml down

test-batch:
	$(PYTHON) test/run_batch_test.py $(TEST_BATCH_ARGS)
