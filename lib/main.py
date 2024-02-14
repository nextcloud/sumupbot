"""Example of an application(SummarAI) that uses Talk Bot APIs."""

############
#
# Talk Bot App with Transformers
#
# https://cloud-py-api.github.io/nc_py_api/NextcloudTalkBotTransformers.html
#
#
# Run: text-generation-webui to generate a api access to 127.0.0.1:5000 which will be used as input for summary
#
#
############

import os
import re
import hmac
import json
import httpx
import typing
import asyncio
import logging
import hashlib
import datetime
import xml.etree.ElementTree as ET

from typing import Annotated
from datetime import datetime
from base64 import b64encode, b64decode
from transformers import pipeline
from contextlib import asynccontextmanager
from nc_py_api import talk_bot, AsyncNextcloudApp, NextcloudApp
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, Depends, FastAPI, Response, Request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron.fields import BaseField
from huggingface_hub import \
    snapshot_download  # missing in docu - https://cloud-py-api.github.io/nc_py_api/NextcloudTalkBotTransformers.html
from nc_py_api.ex_app import (
    run_app,
    set_handlers,
    anc_app,
    atalk_bot_msg,
    nc_app,
    LogLvl,
    persistent_storage,  # missing in docu - https://cloud-py-api.github.io/nc_py_api/NextcloudTalkBotTransformers.html
)
from random import choice
from string import ascii_lowercase, ascii_uppercase, digits

os.environ["APP_HOST"] = "0.0.0.0"
os.environ["APP_ID"] = "summarai"
os.environ["APP_PORT"] = "9032"
os.environ["APP_SECRET"] = "12345"
os.environ["APP_VERSION"] = "1.0.0"
os.environ["NEXTCLOUD_URL"] = "http://localhost/nc_beta28"
os.environ["APP_PERSISTENT_STORAGE"] = "/tmp/"

logging.basicConfig(filename='/tmp/app.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('apscheduler').setLevel(logging.DEBUG)


# The same stuff as for usual External Applications
@asynccontextmanager
async def lifespan(_app: FastAPI):
    set_handlers(APP, enabled_handler)
    yield


APP = FastAPI(lifespan=lifespan)
# We define bot globally, so if no `multiprocessing` module is used, it can be reused by calls.
# All stuff in it works only with local variables, so in the case of multithreading, there should not be problems.
SUMMARAI = talk_bot.TalkBot(f"/{os.environ['APP_ID']}", f"{os.environ['APP_ID'].capitalize()}",
                                 f"Usage: @{os.environ['APP_ID']} add <daily execution time - eg. 17:00> / @{os.environ['APP_ID']} list / @{os.environ['APP_ID']} delete <job_id> / @{os.environ['APP_ID']} help")

scheduler = BackgroundScheduler()
scheduler.start()

available_params = ['add', 'list', 'delete', 'help']
chat_log={}

def task_type_available(json_data, task_type_id):
    for type_info in json_data['types']:
        if type_info['id'] == task_type_id:
            return True
    return False

def process_topics(input_string):
    # Split the string into lines
    lines = input_string.split('\n')
    processed_lines = []

    for line in lines:
        # Remove leading and trailing whitespace
        trimmed_line = line.strip()
        # Check if the line is not empty
        if trimmed_line:
            # Ensure the line starts with "- *", even if it already starts with "-" or "*"
            if not trimmed_line.startswith("- *"):
                # If it starts with "-", directly add "*", else add "- *"
                if trimmed_line.startswith("-"):
                    # Ensure not to duplicate "*"
                    if not trimmed_line.startswith("- *"):
                        trimmed_line = f"- *{trimmed_line[2:]}"
                elif trimmed_line.startswith("*"):
                    trimmed_line = f"- {trimmed_line}"
                else:
                    trimmed_line = f"- *{trimmed_line}"
            # Remove trailing space or tab before "*"
            trimmed_line = re.sub(r"[\t ]+\*$", "*", trimmed_line)
            # Ensure the line ends with "*", if it does not already
            if not trimmed_line.endswith("*"):
                trimmed_line += "*"
        processed_lines.append(trimmed_line)

    # Join the processed lines back into a single string
    processed_string = '\n'.join(processed_lines)
    return processed_string


def is_valid_time(hour, minute):
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return True
    else:
        return False


#def summarize_talk_bot_process_request(message: talk_bot.TalkBotMessage):
def summarai_talk_bot_process_request(message: talk_bot.TalkBotMessage, chat_messages: list, conversation_name: str, conversation_token: str):
    nc_app = NextcloudApp()

    # set_user needed for accessing the Talk API to get all messages
    # waiting for https://github.com/nextcloud/spreed/issues/10401 as
    # talk api doesnt provide the feature to get the participants of a room
    # and therefore we dont know which user we should use as the user has to be
    # member of the room to get the messages. 
    # nc_app.users_list() just provides all users of the system - therefore not usable in this case
    #nc_app.set_user('<username_of_the_room_goes_here>')

    # Define the path of the file
    print("\033[1;42mReceiving message...\033[0m", flush=True)
    try:
        if len(chat_messages) == 0:
            print("No message received...", flush=True)
            return

        ##############
        #
        # 1. Check for availbale task type
        #
        ##############
        try:
            tasktype_endpoint = '/ocs/v2.php/textprocessing/tasktypes'
            tasktype_result: dict = nc_app.ocs(method="GET", path=tasktype_endpoint)
        except Exception as e:
            logging.error(f"An error occurred while checking {tasktype_endpoint}: {e}")
            return

        # Check for the specific task type ID
        task_type = "OCP\\TextProcessing\\SummaryTaskType"
        is_available = task_type_available(tasktype_result, task_type)
        if not is_available:
            logging.error(f"The neccessary task type: {task_type} is not available")
            return Response()

        ##############
        #
        # 2. Get Chat messages of the chatroom
        #
        ##############
        # chat_messages = nc_app.talk.receive_messages(conversation_token, limit=200)
        # as this doesnt work because of missing capability in TalkAPI ( https://github.com/nextcloud/spreed/issues/10401 ) we need to use the created array for chat_logs

        ##############
        #
        # 3. Prepare the messages in a format thats good for summarizing
        #
        ##############
        # Go through all the received chat messages and get only the messages of the current day
        # Skip all messages from bots, so that only user messages will be used for a summary
        
        day = datetime.today()
        skipper = [
            f"@{os.environ['APP_ID']} ",
            f"@{os.environ['APP_ID']}",
        ]

        c = 0
        messages = f"{day}"
        for el in chat_messages:
            date_str = el.split(' ')[0]
            time_str = el.split(' ')[1]
            username = el.split(' ')[2]
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            if dt.date() != day.date() or any(username.startswith(pattern) for pattern in skipper):
                continue

            msg = f"{el}"
            messages = f"{msg}\n\n" + f"{messages}"
            c += 1

        if c == 0:
            logging.info("The chatroom didnt had a converstation today")
            return

        ##############
        #
        # 4. Schedule a task with textprocessing-api via OCS
        #
        ##############

        chunk_size = 2000
        try:
            add_task_endpoint = '/ocs/v2.php/textprocessing/schedule'
            add_task_ocs_url = f'{os.environ["NEXTCLOUD_URL"]}{add_task_endpoint}'
            # Ensure the message is a string
            messages = str(messages)

            summary = ""
            all_messages = ""
            all_message_chunks = ""
            # Loop over the message in increments of chunk_size
            # as the limitation is somewhere of 4000 characters for a summary and the daily chat could me longer than that
            # we split the chat into chunks and create multiple summarize requests which responses we concatenate together in the end

            for i in range(0, len(messages), chunk_size):
                # Slice the message from the current index i up to i + chunk_size
                # message_chunk = f"Chatroom: {conversation_name} at {day} \n \n \n { messages[i:i + chunk_size] }"
                message_chunk = f"{messages[i:i + chunk_size]}"

                all_message_chunks += f"{messages[i:i + chunk_size]}\n"
                # Create an MD5 hash object
                hash_object = hashlib.md5()
                hash_object.update(message_chunk.encode())
                md5_hash = hash_object.hexdigest()

                # we need to limit the messages characters, otherwise we get a <Response [414 Request-URI Too Long]> if it exceeds 5400 characters
                data = {
                    "input": f"""  You are a secretary and tasked with providing an insightful and succint summarization of a chat log.
                                    The chat log will be provided to you below contained within the following tags:

                                    ***CHAT_LOG_START***
                                    and
                                    ***CHAT_LOG_END*** 

                                    The chatlog will be formatted as follows:
                                    2024-01-31 17:33:27 Participant 1 name: message
                                    2024-01-31 17:32:22 Participant 2 name: message
                                    ...and so on...

                                    Here is the chat log you should summarize:
                                    ***CHAT_LOG_START***
                                    {message_chunk}
                                    ***CHAT_LOG_END***
                                    Now, please provide an insighful summary of the provided chat log.
                                    Please, do not leave out any important facts! But keep the summary still compact so that its readable in roughly 30 seconds.
                                """,
                    "type": task_type,
                    "appId": os.environ["APP_ID"],
                    "identifier": md5_hash
                }
                add_task_result = nc_app.ocs(method="POST", path=add_task_ocs_url, json=data)
                # Accessing values by keys
                for _, value in add_task_result.items():
                    #print(f"\033[1;31moutput\033[0m {value['output']}", flush=True)
                    summary += f" {value['output']}"

            summary = summary.lstrip(" \t")

            # check if the created summary exceeds the possible size, if yes we have to create another ai job to summarize the summary
            if len(messages) > chunk_size:
                try:
                    # Create an MD5 hash object
                    hash_object = hashlib.md5()
                    hash_object.update(summary.encode())
                    md5_hash = hash_object.hexdigest()

                    # we need to limit the messages characters, otherwise we get a <Response [414 Request-URI Too Long]> if it exceeds 5400 characters
                    data = {
                        "input": f"""  You are a secretary and tasked with providing an insightful and succint summarization of a chat log.
                                        The chat log will be provided to you below contained within the following tags:

                                        ***CHAT_LOG_START***
                                        and
                                        ***CHAT_LOG_END*** 

                                        The chatlog will be formatted as follows:
                                        summary of all messages
                                        ...and so on...

                                        Here is the chat log you should summarize:
                                        ***CHAT_LOG_START***
                                        {summary}
                                        ***CHAT_LOG_END***
                                        Now, please provide an insighful summary of the provided chat log.
                                        Please, do not leave out any important facts! But keep the summary still compact so that its readable in roughly 30 seconds.
                                    """,
                        "type": task_type,
                        "appId": os.environ["APP_ID"],
                        "identifier": md5_hash
                    }

                    summary = ""
                    add_task_result = nc_app.ocs(method="POST", path=add_task_ocs_url, json=data)
                    # Accessing values by keys
                    for _, value in add_task_result.items():
                        summary += f" {value['output']}"
                    summary = summary.lstrip(" \t")

                except Exception as e:
                    print("Error: Failed to summarize the summary", flush=True)

            # Create the topics out of the summary
            try:
                # Create an MD5 hash object
                hash_object = hashlib.md5()
                hash_object.update(all_messages.encode())
                md5_hash = hash_object.hexdigest()
                # we need to limit the messages characters, otherwise we get a <Response [414 Request-URI Too Long]> if it exceeds 5400 characters
                topic_data = {
                    "input": f"""  You are tasked with providing an insightful and succint summarization in topics of a summary.
                                    The topics should be seperated in new lines, each line should begin with a trailing dash
                                    The summary will be provided to you below contained within the following tags:
                                    ***CHAT_LOG_START***
                                    and
                                    ***CHAT_LOG_END*** 
                                    Here is the summary you should create topics from:
                                    ***CHAT_LOG_START***
                                    {summary}
                                    ***CHAT_LOG_END***
                                    Now, please provide an insighful topics of the summary.
                                    Please, do not leave out any important topics! The topics should be seperated in new lines.
                                """,
                    "type": task_type,
                    "appId": os.environ["APP_ID"],
                    "identifier": md5_hash
                }

                add_topic_result = nc_app.ocs(method="POST", path=add_task_ocs_url, json=topic_data)
                # Accessing values by keys
                topic_output=""
                for _, value in add_topic_result.items():
                    print(f"\033[1;31mTopic output\033[0m {value['output']}", flush=True)
                    topic_output += f" {value['output']}"
                topics = re.sub(r"^[\t ]+", "", f"{topic_output}")
                topics = process_topics(topics)

            except Exception as e:
                print(f"\033[1;31mError\033[0m Cant create topics {e}")
                topics = ""
                pass

            if topics:
                # Finally - send the summarized message to the chat
                msg = f"""\n**Topics:**\n{topics}\n\n**Summary:**\n\n*{summary}*"""
                print(msg, flush=True)
                SUMMARAI.send_message(f"""\n**Topics:**\n{topics}\n\n**Summary:**\n\n{summary}""", message)
            else:
                SUMMARAI.send_message(f"""\n**Summary:**\n{summary}""", message)

        except Exception as e:
            logging.error(f"1. An error occurred: {e}")
            # SUMMARAI.send_message(f"```1 An error occurred: {e}```", message)

    except Exception as e:
        logging.error(f"2. An error occurred: {e}")
        # SUMMARAI.send_message(f"```2 An error occurred: {e}```", message)


def is_numbers_and_colon(s):
    for char in s:
        if not (char.isdigit() or char == ':'):
            return False
    return True


def help_message(message, text):
    SUMMARAI.send_message(
        f"\n\n**{os.environ['APP_ID']}**:\n*{text}*\n\n**Commands:**\n```\nAdd a SummarAI job (The job will be executed daily at the same time):\n\t@{os.environ['APP_ID']} add <hour>:<minute>\n\nList scheduled SummarAI jobs:\n\t@{os.environ['APP_ID']} list\n\nDelete a SummarAI job:\n\t@{os.environ['APP_ID']} delete <job_id>\n\nPrints a help message:\n\t@{os.environ['APP_ID']} help\n```",
        message)


@APP.post(f"/{os.environ['APP_ID']}")
async def summarai(
    message: Annotated[talk_bot.TalkBotMessage, Depends(atalk_bot_msg)],
    nc: Annotated[NextcloudApp, Depends(anc_app)],
):
    conversation_token = getattr(message, 'conversation_token')
    conversation_name = getattr(message, 'conversation_name')
    if message.object_content["message"].startswith(f"@{os.environ['APP_ID']} "):
        param = message.object_content["message"].split(" ")[1]
        #######
        #
        # if we dont have a available parameter than we expect it is a scheduled job and check/process it further
        #
        #######

        if param not in available_params:
            text = "You gave me a command i don't understand, these are available commands"
            help_message(message, text)
            return Response()
        else:

            #########
            #
            # Check for parameters that arent times
            #
            #########
            if param == 'add':
                hour_minute = message.object_content["message"].split(" ")[2]

                if not is_numbers_and_colon(hour_minute):
                    SUMMARAI.send_message(f"```Usage: @{os.environ['APP_ID']} <hour>:<minute>```", message)
                    return Response()

                try:
                    # Splitting the string into hour and minute
                    hour, minute = hour_minute.split(":")
                    try:
                        hour = int(hour)
                        minute = int(minute)
                    except ValueError:
                        info_msg = "Hour and/or minute(s) are not integers."
                        logging.error(info_msg)
                        SUMMARAI.send_message(f"```{info_msg}```", message)
                        return Response()

                    if not is_valid_time(hour, minute):
                        logging.error(f"Its not a valid time {hour}:{minute}:00")
                        SUMMARAI.send_message(
                            f"```Its not a valid time - please use @{os.environ['APP_ID']} hour:minute to schedule the bot for execution```",
                            message)
                        return Response()

                    # Parameters for the new job
                    new_job_hour = int(hour)
                    new_job_minute = int(minute)
                    new_job_hash = f"{conversation_token}_{hashlib.md5(f'{conversation_token}_{conversation_name}_{new_job_hour}_{new_job_minute}'.encode()).hexdigest()}"

                    # Check if a similar job already exists
                    job_exists = False
                    job_hash = new_job_hash

                    for job in scheduler.get_jobs():
                        trigger = job.trigger
                        job_id = job.id

                        old_conversation_token = job.id.split("_")[0]

                        if isinstance(trigger, CronTrigger):
                            job_hour = trigger.fields[trigger.FIELD_NAMES.index('hour')]
                            job_minute = trigger.fields[trigger.FIELD_NAMES.index('minute')]
                            job_day_of_week = trigger.fields[trigger.FIELD_NAMES.index('day_of_week')]

                            old_job_hash = f"{old_conversation_token}_{hashlib.md5(f'{old_conversation_token}_{conversation_name}_{job_hour}_{job_minute}'.encode()).hexdigest()}"

                            if isinstance(job_hour, BaseField):
                                job_hour = job_hour.expressions[0]
                                job_hour = int(f"{hour}")

                            if isinstance(job_minute, BaseField):
                                job_minute = job_minute.expressions[0]
                                job_minute = int(f"{job_minute}")

                            if (
                                    job_hour == new_job_hour and job_minute == new_job_minute and old_job_hash == new_job_hash):
                                job_exists = True
                                break

                    if job_exists:

                        if job_hour <= 9:
                            job_hour = f"0{job_hour}"
                        if job_minute <= 9:
                            job_minute = f"0{job_minute}"

                        SUMMARAI.send_message(
                            f"```Skip - A {os.environ['APP_ID']} job already exists at {job_hour}:{job_minute}:00 for '{conversation_name}' with the id: {job.id}```",
                            message)
                        return Response()

                    ##########
                    #
                    # Finally - Add the job with the conversation name (Name of the chatroom / Chat)
                    #
                    ##########

                    scheduler.add_job(lambda: summarai_talk_bot_process_request(message=message, chat_messages=chat_log[conversation_token], conversation_name=conversation_name, conversation_token=conversation_token), 'cron', hour=hour,
                                      minute=minute, day_of_week='*', id=job_hash)
                    if hour <= 9:
                        hour = f"0{hour}"
                    if minute <= 9:
                        minute = f"0{minute}"
                    SUMMARAI.send_message(
                        f"```New: Added a daily SummarAI task at {hour}:{minute}:00 for '{conversation_name}' with the id: {job_hash}```",
                        message)
                except Exception as e:
                    logging.error(f"A error occured: {e}")
                    SUMMARAI.send_message(f"```Error {e}```", message)

            elif param == 'list':
                jobs = scheduler.get_jobs()
                job_list = []
                for idx, job in enumerate(jobs):
                    logging.info(f"Job ID: {job.id}, Next Run Time: {job}")
                    trigger = job.trigger

                    job_hour = int(f"{trigger.fields[trigger.FIELD_NAMES.index('hour')].expressions[0]}")
                    if job_hour <= 9:
                        job_hour = f"0{job_hour}"

                    job_minute = int(f"{trigger.fields[trigger.FIELD_NAMES.index('minute')].expressions[0]}")
                    if job_minute <= 9:
                        job_minute = f"0{job_minute}"

                    job_day_of_week = f"{trigger.fields[trigger.FIELD_NAMES.index('day_of_week')].expressions[0]}"
                    if job_day_of_week == '*':
                        job_day_of_week = 'Daily'

                    if f"{job.id}".startswith(f"{conversation_token}_"):
                        job_list.append(f"{idx + 1}. Job ID: {job.id} {job_hour}:{job_minute}:00 {job_day_of_week}")

                # Check if job_list is empty
                if not job_list:
                    job_list.append(f"No {os.environ['APP_ID']} job scheduled for '{conversation_name}'")

                job_list_str = '\n'.join(job_list)

                SUMMARAI.send_message(f"```Scheduled Jobs:\n{job_list_str}\n```", message)

            elif param == 'delete':
                try:
                    job_id_to_delete = message.object_content["message"].split(" ")[2]
                except:
                    job_id_to_delete = False

                if not job_id_to_delete:
                    SUMMARAI.send_message(
                        f"```No Job ID to delete given - use '@{os.environ['APP_ID']} list' to get a list of scheduled job ids```",
                        message)
                    return Response()

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
                    SUMMARAI.send_message(
                        f"```You are not allowed to do that - you need to be member of the room```", message)
                    return Response()

                if job_deleted:
                    SUMMARAI.send_message(f"```Deleted Job {job_id_to_delete} from '{conversation_name}'```",
                                               message)
                    return Response()
            elif param == 'help':
                text = "I am happy to help, these are commands you can use"
                help_message(message, text)
                return Response()
            else:
                text = "Yes I am here and listening"
                help_message(message, text)
                return Response()

    elif (message.object_content["message"].startswith(f"@{os.environ['APP_ID']}") and message.object_content[
        "message"].endswith(f"@{os.environ['APP_ID']}")) or (
            message.object_content["message"].startswith(f"@{os.environ['APP_ID']} ") and message.object_content[
        "message"].endswith(f"@{os.environ['APP_ID']} ")):
        text = "Hi! I am here and listening"
        help_message(message, text)
        return Response()
    else:
        if conversation_token not in chat_log:
            chat_log[conversation_token] = []

        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Message will be structured like this
        # 2024-01-31 17:33:27 Participant 1 name: message
        chat_message = f'{current_datetime} {message.actor_display_name}: {message.object_content["message"]}'
        chat_log[conversation_token].append(chat_message)

        print(f"\033[1;44mChat log:\033[0m\033[1;34m {conversation_token} - {conversation_name} \033[0m", chat_log[conversation_token], flush=True)

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
        SUMMARAI.enabled_handler(enabled, nc)
    except Exception as e:
        return str(e)
    return ""


if __name__ == "__main__":
    run_app("main:APP", log_level="trace", reload=True)
