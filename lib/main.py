"""Summary Talk Bot"""

import hashlib
import logging
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated

import tzlocal
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.cron.fields import BaseField
from fastapi import Depends, FastAPI, Response
from nc_py_api import Nextcloud, NextcloudApp, talk_bot
from nc_py_api.ex_app import (
    atalk_bot_msg,
    run_app,
    set_handlers,
    setup_nextcloud_logging,
)
from timelength import TimeLength

#### For local dev purposes
# os.environ["APP_HOST"] = "0.0.0.0"
# os.environ["APP_ID"] = "summary_bot"
# os.environ["APP_DISPLAY_NAME"] = "Summary Bot"
# os.environ["APP_PORT"] = "9031"
# os.environ["APP_SECRET"] = "12345"
# os.environ["APP_VERSION"] = "1.0.0"
# os.environ["NEXTCLOUD_URL"] = "http://nextcloud.local"
# os.environ["APP_PERSISTENT_STORAGE"] = "/tmp/"

# Imported here to register environment variables before importing store (only for local dev purposes)
import store


class LLMException(Exception):
    pass


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(os.environ["APP_ID"])
logger.setLevel(logging.DEBUG)
setup_nextcloud_logging(os.environ["APP_ID"], logging.WARNING)

# The same stuff as for usual External Applications
@asynccontextmanager
async def lifespan(app: FastAPI):
    set_handlers(app, enabled_handler)
    yield


APP = FastAPI(lifespan=lifespan)

# We define bot globally, so if no `multiprocessing` module is used, it can be reused by calls.
# All stuff in it works only with local variables, so in the case of multithreading, there should not be problems.
BOT = talk_bot.TalkBot(
    f"/{os.environ['APP_ID']}",
    f"{os.environ['APP_DISPLAY_NAME']}",
    "For usage instructions, type: @summary help",
)

SUMMARY_TEMPLATE = """You are a secretary and tasked with providing an insightful and succint summarization of a chat log.
The chat log will be provided to you below will be defined in an XML format inside triple single quotes.
Each message will be encapsulated in a <msg> tag, with the following subtags:
<ts> for the timestamp of the message
<at> for the name of the participant
<cnt> for the message content

Here is the chat log from the room called "{conversation_name}" that you should summarize, do not mention the room explicitly:

'''
{messages}
'''


Now, please provide an insighful summary of the provided chat log and use human-readable time references for time related information.
Use bullet points to list the most important facts and keep the summary concise and readable in roughly 30 seconds.
""" # noqa: E501

PROMPT_WINDOW = 16_000 - 4_000
"""Most models (proprietory and local) have an effective context length of 16000 tokens. We leave 4000 tokens for the
generated summary and 12000 tokens for the context."""

MAX_WORDS = int(PROMPT_WINDOW // 1.5)
"""Taking 1 word ~ 1.5 tokens to be on the safe side for languages other than English"""

MAX_CHARACTERS = MAX_WORDS * 5


scheduler = BackgroundScheduler()
scheduler.start()

# We need to use ThreadPoolExecutor for message store and taskproc API calls
executor = ThreadPoolExecutor(max_workers=10)


available_params = ["add", "list", "delete", "help"]


def error_handler(custom_err_msg: str, message: talk_bot.TalkBotMessage | None = None):
    logger.error("An error occurred: %s", custom_err_msg)
    traceback.print_exc()
    if message:
        BOT.send_message(f"```{custom_err_msg}```", message)


def is_valid_time(hour, minute):
    return bool(0 <= hour <= 23 and 0 <= minute <= 59)


def is_task_type_available():
    try:
        nc = Nextcloud()
        tasktype_result = nc.ocs(method="GET", path="/ocs/v2.php/taskprocessing/tasktypes")
    except Exception:
        error_handler("An error occurred while fetching the list of available tasktypes")
        return False

    # Check for the specific task type ID
    task_type = "core:text2text"
    if not isinstance(tasktype_result, dict) or task_type not in tasktype_result.get("types", {}):
        error_handler(f"The neccessary task type: {task_type} is not available")
        return False

    return True


def validate_task_response(response) -> dict:
    if not isinstance(response, dict) or "task" not in response:
        raise LLMException("Failed to create Nextcloud TaskProcessing task")

    task = response["task"]

    if not isinstance(task, dict) or "id" not in task or "status" not in task or "output" not in task:
        raise LLMException("Invalid Nextcloud TaskProcessing task response")

    return task


def ocs_get_summary(messages_str: str, conversation_name: str) -> str:
    nc = Nextcloud()
    prompt = SUMMARY_TEMPLATE.format(messages=messages_str, conversation_name=conversation_name)
    response = nc.ocs(
        "POST",
        "/ocs/v2.php/taskprocessing/schedule",
        json={"type": "core:text2text", "appId": os.environ["APP_ID"], "input": {"input": prompt}},
    )

    try:
        task = validate_task_response(response)
        logger.debug("Task with ID %s created", task["id"])

        i = 0
        # wait for 30 minutes
        while task["status"] != "STATUS_SUCCESSFUL" and task["status"] != "STATUS_FAILED" and i < 60 * 6:
            time.sleep(5)
            i += 1
            response = nc.ocs("GET", f"/ocs/v2.php/taskprocessing/task/{task['id']}")
            task = validate_task_response(response)
            logger.debug("Task (%s) status: %s", task["id"], task["status"])
    except Exception as e:
        raise LLMException("Failed to create Nextcloud TaskProcessing task") from e

    if task["status"] != "STATUS_SUCCESSFUL":
        raise LLMException("Nextcloud TaskProcessing Task failed: " + task["status"])

    if "output" not in task or "output" not in task["output"]:
        raise LLMException("No output in Nextcloud TaskProcessing task")

    return task["output"]["output"]


def sched_process_request(message: talk_bot.TalkBotMessage, job_hash: str):
    # set_user needed for accessing the Talk API to get all messages
    # waiting for https://github.com/nextcloud/spreed/issues/10401 as
    # talk api doesnt provide the feature to get the participants of a room
    # and therefore we dont know which user we should use as the user has to be
    # member of the room to get the messages.
    # nc_app.users_list() just provides all users of the system - therefore not usable in this case
    # nc_app.set_user('<username_of_the_room_goes_here>')

    logger.debug("\033[1;42mProcessing request (%s)...\033[0m", job_hash)

    ##############
    #
    # 1. Get Chat messages of the chatroom
    #
    ##############
    # messages = nc_app.talk.receive_messages(conversation_token, limit=200)
    # as this doesnt work because of missing capability in TalkAPI (https://github.com/nextcloud/spreed/issues/10401)
    #   we need to use the created array for chat_logs

    ##############
    #
    # 2. Schedule a task with taskprocessing-api via OCS. This API uses POST requests so we don't need to limit the
    #    messages characters, or fear a <Response [414 Request-URI Too Long]> if it exceeds 5400 characters
    #
    ##############
    last_x_duration_process(message, "1d")


def get_ctx_limited_messages(chat_messages: list[store.ChatMessages]) -> tuple[str, str | None]:
    """Get the last messages that fit into the context window of the model.
        The second return is the cut-off datetime of the messages.
    """

    msgs = ""
    length = 0
    cutoff = None

    for i in range(len(chat_messages) - 1, -1, -1):
        msg = format_message(chat_messages[i])
        if (length := length + len(msg)) > MAX_CHARACTERS:
            cutoff = str(chat_messages[max(0, i-1)].timestamp)
            break

        msgs = msg + "\n" + msgs

    if not msgs:
        return str(chat_messages[0]), None

    return msgs, cutoff


def last_x_duration_process(message: talk_bot.TalkBotMessage, hduration: str = "1d"):
    if not is_task_type_available():
        BOT.send_message("```The required task type to generate the summary is not available```", message)
        return

    timelength_res = TimeLength(hduration)
    if not timelength_res.result.success:
        help_message(
            message,
            "Invalid duration format. Please use '30m' for 30 minutes, '3h40m' for 3 hours and "
            "40 minutes, '1d' for 1 day",
        )
        return

    duration = timedelta(seconds=timelength_res.to_seconds(max_precision=0))
    current_time = datetime.now()
    start_time = current_time - duration
    start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Get the chat messages from the database
        chat_messages = store.ChatMessages \
            .select() \
            .where(store.ChatMessages.room_id == message.conversation_token) \
            .where(store.ChatMessages.timestamp >= start_time_str)

        if chat_messages.count() == 0:
            BOT.send_message(f"There was no conversation since i joined '{message.conversation_name}'", message)
            return
    except Exception:
        error_handler("Error occured while fetching the messages from the database", message)
        return

    (formatted_chat_messages, cutoff) = get_ctx_limited_messages(chat_messages)
    try:
        summary = ocs_get_summary(formatted_chat_messages, message.conversation_name)
        local_tz = tzlocal.get_localzone()
        ai_info = (
            "\u2139\ufe0f *This output was generated by AI. Make sure to double-check."
            f" (All times are in {local_tz.key or 'server\'s'} timezone)*\n"
        )
        if cutoff:
            ai_info += f"\n\n*Note: Messages before \"{cutoff}\" were not included in the summary due to the length limit.*"
        BOT.send_message(f"""**Summary:**\n{summary}\n\n{ai_info}""", message)
    except LLMException:
        error_handler("Could not get a summary from any large language model", message)


def is_numbers_and_colon(s: str):
    return all(char.isdigit() or char == ":" for char in s)


def help_message(message, text):
    BOT.send_message(f"""
**{os.environ["APP_DISPLAY_NAME"]}**:
*{text}*

**Commands:**
```
Create a summary from last 24 hours of chat messages:
    @summary

Create a summary from last provided duration of chat messages ("30m" for 30 minutes, "3h40m" for 3 hours and 40 minutes, "1d" for 1 day):
    @summary <duration>

Add a {os.environ["APP_DISPLAY_NAME"]} job (The job will be executed daily at the same time, in 24-hour format):
    @summary add <hour>:<minute>

List scheduled {os.environ["APP_DISPLAY_NAME"]} jobs:
    @summary list

Delete a {os.environ["APP_DISPLAY_NAME"]} job:
    @summary delete <job_id>

Prints a help message:
    @summary help
```
""", # noqa: E501
        message,
    )


def render_activity_message(message: talk_bot.TalkBotMessage) -> str:
    msg = message.object_content["message"]
    params = message.object_content["parameters"]

    if msg == "Someone voted on the poll {poll}":
        # not important for the summary
        raise NotImplementedError()

    if msg == "{file}":
        return f"{message.actor_display_name} uploaded a file named {params['file']['name']}"

    if msg == "{object}":
        if message.object_content["parameters"]["object"]["type"] == "talk-poll":
            return f"{message.actor_display_name} created a poll titled {params['object']['name']}"
        return f"{message.actor_display_name} created a {params['object']['type']} titled {params['object']['name']}"

    for key in ("user", "user1", "user2", "user3", "user4", "user5", "actor", "poll"):
        if f"{{{key}}}" not in msg:
            continue
        msg = msg.replace(f"{{{key}}}", message.object_content["parameters"][key]["name"])

    return msg


def store_message(tmsg: talk_bot.TalkBotMessage):
    logger.debug("\033[1;44mMessage\033[0m %s", tmsg._raw_data)
    message = ""
    match tmsg.message_type:
        case "Join":
            message = f"{tmsg.actor_display_name} added Summary bot to the conversation"
        case "Leave":
            message = f"{tmsg.actor_display_name} removed Summary bot from the conversation"
        case "Create" if tmsg.object_media_type.startswith("text/") and not tmsg.actor_id.startswith("bot"):
            # text messages which are not from other bots
            message = tmsg.object_content["message"]
        case "Activity":
            try:
                message = render_activity_message(tmsg)
            except KeyError:
                logger.warning("KeyError in parsing the activity message: %s", tmsg.object_content)
                return
            except NotImplementedError:
                return
        case _:
            logger.debug("Unsupported message type: %s", tmsg.message_type)
            return

    try:
        # all calculations based on server time
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        store.ChatMessages.create(
            timestamp=current_datetime,
            room_id=tmsg.conversation_token,
            actor=tmsg.actor_display_name,
            message=message,
        )
    except Exception:
        error_handler("Error occured while storing the message")


def format_message(message: store.ChatMessages) -> str:
    return (
        "<msg>"
        f"<ts>{message.timestamp}</ts>"
        f"<at>{message.actor}</at>"
        f"<cnt>{message.message}</cnt>"
        "</msg>"
    )


def handle_command(message: talk_bot.TalkBotMessage):
    conversation_token = message.conversation_token
    conversation_name = message.conversation_name

    if message.object_content["message"].strip() == f"@summary":
        # Create a summary from last 24 hours of chat messages
        BOT.send_message("```Creating a summary from last 24 hours of chat messages```", message)
        last_x_duration_process(message)
    elif message.object_content["message"].startswith(f"@summary "):
        param = message.object_content["message"].split(" ")[1]
        if param not in available_params:
            if TimeLength(param).result.success:
                # Create a summary from last provided duration of chat messages ("30m" for 30 minutes, "3h40m"
                # for 3 hours and 40 minutes, "1d" for 1 day):
                BOT.send_message(f"```Creating a summary from last {param} of chat messages```", message)
                last_x_duration_process(message, param)
                return

            help_message(
                message,
                "Invalid time string provided, please use '30m' for 30 minutes, '3h40m' for 3 hours and 40 minutes,"
                " '1d' for 1 day",
            ) # noqa: E501
            return

        #########
        #
        # Check for parameters that arent times
        #
        #########
        if param == "add":
            hour_minute = message.object_content["message"].split(" ")[2]

            if not is_numbers_and_colon(hour_minute):
                BOT.send_message("```Usage: @summary <hour>:<minute>```", message)
                return

            try:
                # Splitting the string into hour and minute
                hour, minute = hour_minute.split(":")
                try:
                    hour = int(hour)
                    minute = int(minute)
                except ValueError:
                    BOT.send_message("```Hour and/or minute(s) are not integers.```", message)
                    return

                if not is_valid_time(hour, minute):
                    BOT.send_message(
                        "```Its not a valid time - please use @summary hour:minute to schedule the"
                        " bot for execution```",
                        message,
                    )
                    return

                # Parameters for the new job
                new_job_hour = int(hour)
                new_job_minute = int(minute)
                new_job_hash = f"{conversation_token}_{hashlib.md5(f'{conversation_token}_{conversation_name}_{new_job_hour}_{new_job_minute}'.encode()).hexdigest()}" # noqa: E501, S324

                # Check if a similar job already exists
                job_exists = False
                job_hash = new_job_hash

                job_hour = -1
                job_minute = -1
                for job in scheduler.get_jobs():
                    trigger = job.trigger

                    old_conversation_token = job.id.split("_")[0]

                    if isinstance(trigger, CronTrigger):
                        job_hour = trigger.fields[trigger.FIELD_NAMES.index("hour")]
                        job_minute = trigger.fields[trigger.FIELD_NAMES.index("minute")]
                        job_day_of_week = trigger.fields[trigger.FIELD_NAMES.index("day_of_week")]

                        old_job_hash = f"{old_conversation_token}_{hashlib.md5(f'{old_conversation_token}_{conversation_name}_{job_hour}_{job_minute}'.encode()).hexdigest()}" # noqa: E501, S324

                        if isinstance(job_hour, BaseField):
                            job_hour = job_hour.expressions[0]
                            job_hour = int(f"{hour}")

                        if isinstance(job_minute, BaseField):
                            job_minute = job_minute.expressions[0]
                            job_minute = int(f"{job_minute}")

                        if (
                            job_hour == new_job_hour
                            and job_minute == new_job_minute
                            and old_job_hash == new_job_hash
                        ):
                            job_exists = True
                            break

                if job_exists:
                    if job_hour <= 9:
                        job_hour = f"0{job_hour}"
                    if job_minute <= 9:
                        job_minute = f"0{job_minute}"

                    if job_hour == -1 or job_minute == -1:
                        return

                    BOT.send_message(
                        f"```Skip - A {os.environ['APP_DISPLAY_NAME']} job already exists at {job_hour}:{job_minute}:00 for"
                        f" '{conversation_name}'```",
                        message,
                    )
                    return

                ##########
                #
                # Finally - Add the job with the conversation name (Name of the chatroom / Chat)
                #
                ##########

                scheduler.add_job(
                    lambda: sched_process_request(message=message, job_hash=job_hash),
                    "cron",
                    hour=hour,
                    minute=minute,
                    day_of_week="*",
                    id=job_hash,
                )
                if hour <= 9:
                    hour = f"0{hour}"
                if minute <= 9:
                    minute = f"0{minute}"
                BOT.send_message(
                    f"```New: Added a daily {os.environ["APP_DISPLAY_NAME"]} task at {hour}:{minute}:00 for '{conversation_name}' with the"
                    f" id: {job_hash}```",
                    message,
                )
            except Exception:
                error_handler("Error occured while adding the job", message)

        elif param == "list":
            jobs = scheduler.get_jobs()
            job_list = []
            for idx, job in enumerate(jobs):
                logging.info("Job ID: %s, Next Run Time: %s", job.id, job.next_run_time)
                trigger = job.trigger

                job_hour = int(f"{trigger.fields[trigger.FIELD_NAMES.index('hour')].expressions[0]}")
                if job_hour <= 9:
                    job_hour = f"0{job_hour}"

                job_minute = int(f"{trigger.fields[trigger.FIELD_NAMES.index('minute')].expressions[0]}")
                if job_minute <= 9:
                    job_minute = f"0{job_minute}"

                job_day_of_week = f"{trigger.fields[trigger.FIELD_NAMES.index('day_of_week')].expressions[0]}"
                if job_day_of_week == "*":
                    job_day_of_week = "Daily"

                if f"{job.id}".startswith(f"{conversation_token}_"):
                    job_list.append(f"{idx + 1}. Job ID: {job.id} {job_hour}:{job_minute}:00 {job_day_of_week}")

            # Check if job_list is empty
            if not job_list:
                job_list.append(f"No {os.environ['APP_ID']} job scheduled for '{conversation_name}'")

            job_list_str = "\n".join(job_list)

            BOT.send_message(f"```Scheduled Jobs:\n{job_list_str}\n```", message)

        elif param == "delete":
            try:
                job_id_to_delete = message.object_content["message"].split(" ")[2]
            except Exception:
                job_id_to_delete = False

            if not job_id_to_delete:
                BOT.send_message(
                    "```No Job ID to delete given - use '@summary list' to get a list of scheduled"
                    " job ids```",
                    message,
                )
                return

            #######
            #
            # Check if we are member of the room and therefore allowed to do it
            # otherwise a scheduled job could be deleted from every other room
            #
            #######

            job_deleted = False

            if job_id_to_delete.startswith(f"{conversation_token}_"):
                jobs = scheduler.get_jobs()
                for job in jobs:
                    if job.id == job_id_to_delete:
                        scheduler.remove_job(job_id_to_delete)
                        job_deleted = True
            else:
                BOT.send_message(
                    "```You are not allowed to do that - you need to be member of the room```",
                    message,
                )
                return

            if job_deleted:
                BOT.send_message(
                    f"```Deleted Job {job_id_to_delete} from '{conversation_name}'```",
                    message,
                )
                return
        else:
            help_message(message, "I am happy to help, these are commands you can use")
            return


@APP.post(f"/{os.environ['APP_ID']}")
async def summary_bot(
    message: Annotated[talk_bot.TalkBotMessage, Depends(atalk_bot_msg)],
):
    bot_mention_regex = re.compile("^@summary$|^@summary\\s.*", re.IGNORECASE)
    # store the message if its not a command
    if (
        message.message_type != "Create"
        or not message.object_media_type.startswith("text/")
        or not bot_mention_regex.match(message.object_content["message"].strip())
    ):
        executor.submit(store_message, message)
        return Response()

    executor.submit(handle_command, message)
    return Response()


############
#
# Skeleton app for enabled_handler actualy wrong - doesnt do anything just loggin without enabling/disabling
#
###########


def enabled_handler(enabled: bool, nc: NextcloudApp) -> str:
    print(f"enabled={enabled}")
    try:
        # `enabled_handler` will install or uninstall bot on the server, depending on ``enabled`` parameter.
        BOT.enabled_handler(enabled, nc)
    except Exception:
        error_handler("Error occured while enabling/disabling the bot")
    return ""


if __name__ == "__main__":
    run_app("main:APP", log_level="trace", reload=True)
