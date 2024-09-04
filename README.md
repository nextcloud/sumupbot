
How To Install

==============

  

1. [Install AppAPI](https://apps.nextcloud.com/apps/app_api)

  

2. Create a deployment daemon according to the [instructions](https://cloud-py-api.github.io/app_api/CreationOfDeployDaemon.html#create-deploy-daemon) of the AppPI



3. Run the docker image:
	You can choose if you run the provided docker image from the registry server or if you build it locally yourself

3.1.1 Run the docker image provided by the registry server

	> sudo docker run -ti -v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro -e APP_ID=summarai -e APP_HOST=0.0.0.0 -e APP_PORT=9031 -e APP_SECRET=12345 -e APP_VERSION=<APP_VERSION> -e NEXTCLOUD_URL='<YOUR_NEXTCLOUD_URL_REACHABLE_FROM_INSIDE_DOCKER>' -p 9031:9031 ghcr.io/nextcloud/summarai:latest

3.2.1 **OR**: Build the docker image locally

	Example assuming you are in the source directory of the cloned repository

	> docker build --no-cache -f Dockerfile -t ghcr.io/nextcloud/summarai:latest .  

	Deploy the docker image with Bot to docker.

	Example assuming you are in the source directory of the cloned repository

	> sudo docker run -ti -v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro -e APP_ID=summarai -e APP_HOST=0.0.0.0 -e APP_PORT=9031 -e APP_SECRET=12345 -e APP_VERSION=<APP_VERSION> -e NEXTCLOUD_URL='<YOUR_NEXTCLOUD_URL_REACHABLE_FROM_INSIDE_DOCKER>' -p 9031:9031 ghcr.io/nextcloud/summarai:latest

4. Register the SummarAI Bot

	> (Hint: In both cases, registering manually or via makefile, adjust the json dictionary that it fits your environment/needs)
	
	**Register manually:**
	
	*Example assuming you are in the source directory of your nextcloud instance where occ is located and the default user www-data got execution rights on occ*

    *Unregistering SummarAI*
	> sudo -u www-data php ./occ app_api:app:unregister summarai

    *Registering SummarAI:*
	> sudo -u www-data php ./occ app_api:app:register summarai manual_install --json-info '{ "id": "summarai", "name": "SummarAI", "daemon_config_name": "manual_install", "version": "<APP_VERSION>", "secret": "12345", "host": "192.168.0.199", "port": 9031, "scopes": ["AI_PROVIDERS", "TALK", "TALK_BOT"], "protocol": "http"}' --force-scopes --wait-finish

	**OR**

	**Register via Makefile:**
	
	*Example assuming you are in the source directory of the cloned repository*

	> make register_local
