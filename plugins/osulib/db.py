from sqlalchemy.sql import select, insert, delete

from pcbot.db import engine, db_metadata


def insert_scores(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_scores"]
        statement = insert(table).values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def insert_beatmap(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = insert(table).values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_beatmap(beatmap_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = select(table).where(table.c.id == beatmap_id)
        result = connection.execute(statement)
        return result.fetchone()


def insert_beatmapset(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmapsets"]
        statement = insert(table).values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_beatmapset(beatmapset_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmapsets"]
        statement = select(table).where(table.c.id == beatmapset_id)
        result = connection.execute(statement)
        return result.fetchone()


def delete_user_scores(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_scores"]
        statement = delete(table).where(table.c.user_id == user_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_user_scores(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_scores"]
        statement = select(table).where(table.c.user_id == user_id)
        result = connection.execute(statement)
        return result.all()
