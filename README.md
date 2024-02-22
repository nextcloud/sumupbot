
How To Install

==============

  

1. [Install AppAPI](https://apps.nextcloud.com/apps/app_api)

  

2. Create a deployment daemon according to the [instructions](https://cloud-py-api.github.io/app_api/CreationOfDeployDaemon.html#create-deploy-daemon) of the AppPI

  

3. To deploy a docker image with Bot to docker.

	Example assuming you are in the source directory of the bot:

	> sudo docker run -ti -v
	> -v /etc/localtime:/etc/localtime:ro -v
	> /etc/timezone:/etc/timezone:ro -e APP_ID=summarai -e APP_HOST=0.0.0.0
	> -e APP_PORT=9031 -e APP_SECRET=12345 -e APP_VERSION=1.0.0 -e 	NEXTCLOUD_URL='<YOUR_NEXTCLOUD_URL_REACHABLE_FROM_INSIDE_DOCKER>' -p
	> 9031:9031 summarai:latest

4. Register the SummarAI Bot

	Example assuming you are in the source directory of the bot 
	> (Hint: In both cases, registering manually or via makefile, adjust the json dictionary that it fits your environment/needs)
	
	**Register manually:**
	> sudo -u www-data php ./occ app_api:app:unregister summarai
	> sudo -u www-data php ./occ app_api:app:register summarai manual_install --json-info \  
"{\"appid\":\"summarai\",\"name\":\"SummarAI\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"host\":\"192.168.0.199\",\"port\":9031,  
\"scopes\":[\"AI_PROVIDERS\", \"NOTIFICATIONS\", \"TALK\", \"TALK_BOT\"],\"protocol\":\"http\",\"system_app\":0}" \  
--force-scopes --wait-finish

	**Register via Makefile:**
	> make register_local
