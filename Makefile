.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Welcome to SummarAI bot. Please use \`make <target>\` where <target> is one of"
	@echo " "
	@echo "  Next commands are only for dev environment with nextcloud-docker-dev!"
	@echo "  They should run from the host you are developing on(with activated venv) and not in the container with Nextcloud!"
	@echo "  "
	@echo "  build-push        build image and upload to ghcr.io"
	@echo "  "
	@echo "  run               install SummarAI for Nextcloud Last"
	@echo "  run27             install SummarAI for Nextcloud 27"
	@echo "  "
	@echo "  For development of this example use PyCharm run configurations. Development is always set for last Nextcloud."
	@echo "  First run 'SummarAI' and then 'make registerXX', after that you can use/debug/develop it and easy test."
	@echo "  "
	@echo "  register          perform registration of running 'SummarAI' into the 'manual_install' deploy daemon."
	@echo "  register_local    perform registration of running 'SummarAI' into the 'manual_install' deploy daemon for a local running instance."
	@echo "  register27        perform registration of running 'SummarAI' into the 'manual_install' deploy daemon."

.PHONY: build-push
build-push:
	docker login ghcr.io
	docker buildx build --push --platform linux/arm64/v8,linux/amd64 --tag ghcr.io/nextcloud/summarai:1.0.0 .

.PHONY: run
run:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister summarai --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register summarai docker_dev --json-info \
  "{\"id\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"docker_dev\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\", \"USER_INFO\", \"SYSTEM\", \"TEXT_PROCESSING\"],\"system\":1}" \
  --force-scopes --wait-finish

.PHONY: run27
run27:
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:unregister summarai --silent || true
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:register summarai manual_install --json-info \
  "{\"id\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"docker_dev\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\", \"USER_INFO\", \"SYSTEM\", \"TEXT_PROCESSING\"],\"system\":1}" \
  --force-scopes --wait-finish

.PHONY: register
register:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister summarai --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register summarai manual_install --json-info \
  "{\"id\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\", \"USER_INFO\", \"SYSTEM\", \"TEXT_PROCESSING\"],\"system\":1}" \
  --force-scopes --wait-finish

.PHONY: register_local
register_local:
	sudo -u www-data php /var/www/nc_29/occ app_api:app:unregister summarai --silent || true
	sudo -u www-data php /var/www/nc_29/occ app_api:app:register summarai manual_install --json-info \
  "{\"id\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"host\":\"192.168.0.199\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\", \"TEXT_PROCESSING\"],\"protocol\":\"http\",\"system\":1}" \
  --force-scopes --wait-finish

.PHONY: register27
register27:
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:unregister summarai --silent || true
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:register summarai manual_install --json-info \
  "{\"id\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"port\":9031,\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\", \"USER_INFO\", \"SYSTEM\", \"TEXT_PROCESSING\"],\"system\":1}" \
  --force-scopes --wait-finish
