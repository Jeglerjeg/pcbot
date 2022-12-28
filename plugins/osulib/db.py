from datetime import datetime

from sqlalchemy import update
from sqlalchemy.sql import select, insert, delete

from pcbot.db import engine, db_metadata


def insert_beatmap(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = insert(table).prefix_with('OR IGNORE').values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_recent_events(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = select(table).where(table.c.id == user_id)
        result = connection.execute(statement)
        return result.fetchone()


def insert_recent_events(user_id: int):
    new_recent_events = {"id": user_id, "last_pp_notification": datetime.utcnow().timestamp()}
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = insert(table).values(new_recent_events)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def update_recent_events(user_id: int, old: dict, pp: bool = False):
    updated_recent_events = {"id": user_id,
                             "last_pp_notification": datetime.utcnow().timestamp()
                             if pp else old["last_pp_notification"]}
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = update(table).where(table.c.id == user_id).values(updated_recent_events)
        result = connection.execute(statement)
        return result.fetchone()


def delete_recent_events(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = delete(table).where(table.c.id == user_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_beatmap(beatmap_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = select(table).where(table.c.id == beatmap_id)
        result = connection.execute(statement)
        return result.fetchone()


def delete_beatmap(beatmap_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = delete(table).where(table.c.id == beatmap_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def insert_beatmapset(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmapsets"]
        statement = insert(table).prefix_with('OR IGNORE').values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_beatmapset(beatmapset_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmapsets"]
        statement = select(table).where(table.c.id == beatmapset_id)
        result = connection.execute(statement)
        return result.fetchone()


def delete_beatmapset(beatmapset_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmapsets"]
        statement = delete(table).where(table.c.id == beatmapset_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()
