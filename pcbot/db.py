import asyncio

from sqlalchemy import create_engine, MetaData, text, event, Table, Column, Integer, Boolean, String, Float, BLOB, \
    DateTime

engine = create_engine("sqlite+pysqlite:///bot.db", echo=False, future=True)
db_metadata = MetaData()


def get_moderate_db():
    Table(
        "moderate",
        db_metadata,
        Column("guild_id", Integer, unique=True),
        Column("nsfwfilter", Boolean),
        Column("changelog", Boolean)
    )


def get_summary_db():
    Table(
        "summary_messages",
        db_metadata,
        Column("content", String(4000), nullable=False),
        Column("channel_id", Integer, nullable=False),
        Column("author_id", Integer, nullable=False),
        Column("bot", Boolean)
    )


def get_wyr_db():
    Table(
        "questions",
        db_metadata,
        Column("choice_1", String, nullable=False),
        Column("choice_2", String, nullable=False),
        Column("choice_1_answers", Integer),
        Column("choice_2_answers", Integer)
    )


def get_linked_osu_profiles_db():
    Table(
        "linked_osu_profiles",
        db_metadata,
        Column("id", Integer, nullable=False, primary_key=True, autoincrement=False),
        Column("osu_id", Integer, nullable=False),
        Column("home_guild", Integer, nullable=False),
        Column("mode", Integer, nullable=False),
        Column("update_mode", String, nullable=False),
    )


def get_osu_users_db():
    Table(
        "osu_users",
        db_metadata,
        Column("discord_id", Integer, nullable=False, primary_key=True, autoincrement=False),
        Column("id", Integer, nullable=False, autoincrement=False),
        Column("username", String, nullable=False),
        Column("avatar_url", String, nullable=False),
        Column("country_code", String, nullable=False),
        Column("mode", Integer, nullable=False),
        Column("pp", Float, nullable=False),
        Column("min_pp", Float, nullable=False),
        Column("accuracy", Float, nullable=False),
        Column("country_rank", Integer, nullable=False),
        Column("global_rank", Integer, nullable=False),
        Column("max_combo", Integer, nullable=False),
        Column("ranked_score", Integer, nullable=False),
        Column("ticks", Integer, nullable=False),
        Column("time_cached", Integer, nullable=False),
    )


def get_osu_events_db():
    Table(
        "osu_recent_events",
        db_metadata,
        Column("id", Integer, nullable=False, primary_key=True, autoincrement=False),
        Column("last_pp_notification", Integer, nullable=False),
        Column("last_recent_notification", Integer, nullable=False),
    )


def get_osu_beatmaps_db():
    Table(
        "beatmaps",
        db_metadata,
        Column("accuracy", Float),
        Column("ar", Float),
        Column("beatmapset_id", Integer),
        Column("checksum", String),
        Column("max_combo", Integer),
        Column("bpm", Float),
        Column("convert", Boolean),
        Column("count_circles", Integer),
        Column("count_sliders", Integer),
        Column("count_spinners", Integer),
        Column("cs", Integer),
        Column("difficulty_rating", Float),
        Column("drain", Integer),
        Column("hit_length", Integer),
        Column("id", Integer, unique=True),
        Column("mode", Integer),
        Column("passcount", Integer),
        Column("playcount", Integer),
        Column("ranked", Integer),
        Column("status", String),
        Column("total_length", Integer),
        Column("user_id", Integer),
        Column("version", String),
        Column("time_cached", DateTime)
    )


def get_osu_beatmapset_db():
    Table(
        "beatmapsets",
        db_metadata,
        Column("artist", String),
        Column("artist_unicode", String),
        Column("bpm", Float),
        Column("covers", BLOB),
        Column("creator", String),
        Column("favourite_count", Integer),
        Column("id", Integer, unique=True),
        Column("play_count", Integer),
        Column("source", String),
        Column("status", String),
        Column("title", String),
        Column("title_unicode", String),
        Column("ranked", Integer),
        Column("user_id", Integer),
        Column("beatmaps", BLOB),
        Column("time_cached", DateTime)
    )

def get_linked_scoresaber_profiles_db():
    Table(
        "linked_scoresaber_profiles",
        db_metadata,
        Column("id", Integer, nullable=False, primary_key=True, autoincrement=False),
        Column("scoresaber_id", Integer, nullable=False),
        Column("home_guild", Integer, nullable=False),
        Column("update_mode", String, nullable=False),
    )

def get_scoresaber_users_db():
    Table(
        "scoresaber_users",
        db_metadata,
        Column("discord_id", Integer, nullable=False, primary_key=True, autoincrement=False),
        Column("id", Integer, nullable=False, autoincrement=False),
        Column("name", String, nullable=False),
        Column("profile_picture", String, nullable=False),
        Column("country", String, nullable=False),
        Column("pp", Float, nullable=False),
        Column("average_ranked_accuracy", Float, nullable=False),
        Column("country_rank", Integer, nullable=False),
        Column("rank", Integer, nullable=False),
        Column("total_ranked_score", Integer, nullable=False),
        Column("ticks", Integer, nullable=False),
        Column("time_cached", Integer, nullable=False),
        Column("last_pp_notification", Integer, nullable=False)
    )


def create_tables():
    get_moderate_db()
    get_summary_db()
    get_wyr_db()
    get_osu_events_db()
    get_osu_beatmaps_db()
    get_osu_beatmapset_db()
    get_linked_osu_profiles_db()
    get_osu_users_db()
    get_linked_scoresaber_profiles_db()
    get_scoresaber_users_db()
    db_metadata.create_all(engine)


async def vacuum_db():
    await asyncio.sleep(3600 * 24)
    with engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(text("VACUUM"))
        transaction.commit()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-364000")
    cursor.close()


@event.listens_for(engine, "close")
def optimize_sqlite(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA analysis_limit=400")
    cursor.execute("PRAGMA optimize")
    cursor.close()
