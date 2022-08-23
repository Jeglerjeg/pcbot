import asyncio

from sqlalchemy import create_engine, MetaData, text, event, Table, Column, Integer, Boolean, String, Float, BLOB,\
    DateTime

engine = create_engine("sqlite+pysqlite:///bot.db", echo=False, future=True)
db_metadata = MetaData()


def get_moderate_db():
    return Table(
        "moderate",
        db_metadata,
        Column("guild_id", Integer, unique=True),
        Column("nsfwfilter", Boolean),
        Column("changelog", Boolean)
    )


def get_summary_db():
    return Table(
        "summary_messages",
        db_metadata,
        Column("content", String(4000), nullable=False),
        Column("channel_id", Integer, nullable=False),
        Column("author_id", Integer, nullable=False),
        Column("bot", Boolean)
    )


def get_wyr_db():
    return Table(
        "questions",
        db_metadata,
        Column("choice_1", String, nullable=False),
        Column("choice_2", String, nullable=False),
        Column("choice_1_answers", Integer),
        Column("choice_2_answers", Integer)
    )


def get_osu_scores_db():
    return Table(
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


def create_tables():
    get_moderate_db()
    get_summary_db()
    get_wyr_db()
    get_osu_scores_db()
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
    cursor.execute("PRAGMA  cache_size=-128000")
    cursor.close()


@event.listens_for(engine, "close")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA analysis_limit=400")
    cursor.execute("PRAGMA optimize")
    cursor.close()
