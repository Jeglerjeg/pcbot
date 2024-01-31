from datetime import datetime, timezone

from sqlalchemy import update, Row
from sqlalchemy.sql import select, insert, delete

from pcbot.db import engine, db_metadata
from plugins.osulib.config import osu_config
from plugins.osulib.models.user import OsuUser


def migrate_profile_cache():
    if "profiles" in osu_config.data:
        for key, value in osu_config.data["profiles"].items():
            insert_linked_osu_profile(key, value, int(osu_config.data["primary_guild"][key]),
                                      int(osu_config.data["mode"][key]),
                                      osu_config.data["update_mode"][key] if key in osu_config.data["update_mode"]
                                      else "Full")
        del osu_config.data["profiles"]
        del osu_config.data["primary_guild"]
        del osu_config.data["mode"]
        del osu_config.data["update_mode"]
        osu_config.save()


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
    current_time = int(datetime.now(tz=timezone.utc).timestamp())
    new_recent_events = {"id": user_id, "last_pp_notification": current_time, "last_recent_notification": current_time}
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = insert(table).values(new_recent_events)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def update_recent_events(user_id: int, old: Row, pp: bool = False, recent: bool = False):
    current_time = int(datetime.now(tz=timezone.utc).timestamp())
    updated_recent_events = {"id": user_id,
                             "last_pp_notification": current_time
                             if pp else old.last_pp_notification,
                             "last_recent_notification": current_time
                             if recent else old.last_recent_notification
                             }
    with engine.connect() as connection:
        table = db_metadata.tables["osu_recent_events"]
        statement = update(table).where(table.c.id == user_id).values(updated_recent_events)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


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


def get_beatmaps_by_beatmapset_id(beatmapset_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["beatmaps"]
        statement = select(table).where(table.c.beatmapset_id == beatmapset_id)
        result = connection.execute(statement)
        return result.fetchall()


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


def get_linked_osu_profiles():
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = select(table)
        result = connection.execute(statement)
        return result.fetchall()


def get_linked_osu_profile_accounts(osu_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = select(table).where(table.c.osu_id == osu_id)
        result = connection.execute(statement)
        return result.fetchall()


def get_linked_osu_profile(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = select(table).where(table.c.id == user_id)
        result = connection.execute(statement)
        return result.fetchone()


def insert_linked_osu_profile(discord_id: int, osu_id: int, home_guild: int, mode: int, update_mode: str = None):
    new_linked_osu_proile = {"id": discord_id, "osu_id": osu_id, "home_guild": home_guild,
                             "mode": mode, "update_mode": "Full" if not update_mode else update_mode}
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = insert(table).values(new_linked_osu_proile)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def update_linked_osu_profile(discord_id: int, osu_id: int, home_guild: int, mode: int, update_mode: str):
    updated_linked_osu_proile = {"id": discord_id, "osu_id": osu_id, "home_guild": home_guild, "mode": mode,
                                 "update_mode": update_mode}
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = update(table).where(table.c.id == discord_id).values(updated_linked_osu_proile)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def delete_linked_osu_profile(user_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["linked_osu_profiles"]
        statement = delete(table).where(table.c.id == user_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_osu_users():
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        statement = select(table)
        result = connection.execute(statement)
        return result.fetchall()


def delete_osu_users():
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        previous_users = connection.execute(select(table.c.discord_id))
        statement = delete(table)
        connection.execute(statement)
        return len(previous_users.fetchall())


def get_osu_user(discord_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        statement = select(table).where(table.c.discord_id == discord_id)
        result = connection.execute(statement)
        return result.fetchone()


def insert_osu_user(user: OsuUser, discord_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        statement = insert(table).values(user.to_db_query(discord_id, new_user=True))
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def update_osu_user(user: OsuUser, discord_id: int, ticks: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        statement = update(table).where(table.c.discord_id == discord_id).values(user.to_db_query(discord_id,
                                                                                                  ticks=ticks))
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def delete_osu_user(discord_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["osu_users"]
        statement = delete(table).where(table.c.discord_id == discord_id)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()
