APP_VERSION := 1.1.1

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Welcome to Summary Bot. Please use \`make <target>\` where <target> is one of"
	@echo " "
	@echo "  Next commands are only for dev environment with nextcloud-docker-dev!"
	@echo "  They should run from the host you are developing on(with activated venv) and not in the container with Nextcloud!"
	@echo "  "
	@echo "  build-push        build image and upload to ghcr.io"
	@echo "  "
	@echo "  run               install Summary Bot for Nextcloud Last"
	@echo "  "
	@echo "  For development of this example use PyCharm run configurations. Development is always set for last Nextcloud."
	@echo "  First run 'Summary Bot' and then 'make register', after that you can use/debug/develop it and easy test."
	@echo "  "
	@echo "  register          perform registration of running 'Summary Bot' into the 'manual_install' deploy daemon."

.PHONY: build-push
build-push:
	docker login ghcr.io
	docker buildx build --push --platform linux/arm64/v8,linux/amd64 --tag ghcr.io/nextcloud/summary_bot:$(APP_VERSION) --tag ghcr.io/nextcloud/summary_bot:latest .

.PHONY: run
run:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister summary_bot --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register summary_bot docker_dev --json-info \
  "{\"id\":\"summary_bot\",\"name\":\"Summary Bot\",\"daemon_config_name\":\"docker_dev\",\"version\":\"$(APP_VERSION)\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"TALK\", \"TALK_BOT\"]}" \
  --force-scopes --wait-finish

.PHONY: register
register:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister summary_bot --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register summary_bot manual_install --json-info \
  "{\"id\":\"summary_bot\",\"name\":\"Summary Bot\",\"daemon_config_name\":\"manual_install\",\"version\":\"$(APP_VERSION)\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"TALK\", \"TALK_BOT\"]}" \
  --force-scopes --wait-finish
