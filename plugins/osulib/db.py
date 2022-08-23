from sqlalchemy.sql import select, insert, delete

from pcbot.db import engine, db_metadata
from plugins.osulib.models.score import OsuScore


def insert_scores(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_scores"]
        statement = insert(table).values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


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
        score_list = []
        for osu_score in result.all():
            score_list.append(OsuScore(osu_score, db=True))
        return score_list
