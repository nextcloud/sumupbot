"""SQLite Chat Message Store"""

import os

from nc_py_api.ex_app import persistent_storage
from peewee import DateTimeField, IntegerField, Model, SqliteDatabase, TextField

DATABASE_NAME = "chat_messages.db"
database_path = os.path.join(persistent_storage(), DATABASE_NAME)
db = SqliteDatabase(database_path)


class ChatMessages(Model):

    id = IntegerField(primary_key=True)
    timestamp = DateTimeField()
    room_id = TextField()
    actor = TextField()
    message = TextField()

    class Meta:
        """Meta class for ChatMessages model"""

        table_name = "chat_messages"
        indexes = (
            (("room_id", "timestamp"), False),
        )
        database = db


db.connect()
db.create_tables([ChatMessages])
