from sqlalchemy import update
from sqlalchemy.sql import select, insert, delete

from pcbot.db import engine, db_metadata

def get_linked_scoresaber_profile(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["linked_scoresaber_profiles"]
        statement = select(table).where(table.c.id == user_id)
        result = connection.execute(statement)
        return result.fetchone()


def insert_linked_scoresaber_profile(discord_id: int, scoresaber_id: int, home_guild: int, update_mode: str = None):
    new_linked_scoresaber_proile = {"id": discord_id, "scoresaber_id": scoresaber_id, "home_guild": home_guild,
                                    "update_mode": "Full" if not update_mode else update_mode}
    with engine.connect() as connection:
        table = db_metadata.tables["linked_scoresaber_profiles"]
        statement = insert(table).values(new_linked_scoresaber_proile)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def update_linked_scoresaber_profile(discord_id: int, scoresaber_id: int, home_guild: int, update_mode: str):
    updated_linked_scoresaber_proile = {"id": discord_id, "scoresaber_id": scoresaber_id, "home_guild": home_guild,
                                 "update_mode": update_mode}
    with engine.connect() as connection:
        table = db_metadata.tables["linked_scoresaber_profiles"]
        statement = update(table).where(table.c.id == discord_id).values(updated_linked_scoresaber_proile)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def delete_linked_scoresaber_profile(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["linked_scoresaber_profiles"]
        statement = delete(table).where(table.c.id == user_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()