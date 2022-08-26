import asyncio

from sqlalchemy import create_engine, MetaData, text, event, Table, Column, Integer, Boolean, String, Float, BLOB,\
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


def get_osu_scores_db():
    Table(
        "osu_scores",
        db_metadata,
        Column("id", Integer, unique=True),
        Column("best_id", Integer, unique=True),
        Column("user_id", Integer),
        Column("beatmap_id", Integer),
        Column("accuracy", Float),
        Column("mods", BLOB),
        Column("total_score", Integer),
        Column("max_combo", Integer),
        Column("legacy_perfect", Boolean),
        Column("statistics", BLOB),
        Column("passed", Boolean),
        Column("pp", Float),
        Column("rank", String(2)),
        Column("ended_at", DateTime),
        Column("mode", Integer),
        Column("replay", Boolean),
        Column("position", Integer),
        Column("weight", BLOB)
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


def create_tables():
    get_moderate_db()
    get_summary_db()
    get_wyr_db()
    get_osu_scores_db()
    get_osu_beatmaps_db()
    get_osu_beatmapset_db()
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
    cursor.execute("PRAGMA synchronous=normal")
    cursor.execute("PRAGMA cache_size=-364000")
    cursor.close()


@event.listens_for(engine, "close")
def optimize_sqlite(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA analysis_limit=400")
    cursor.execute("PRAGMA optimize")
    cursor.close()
