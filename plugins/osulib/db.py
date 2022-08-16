import bot
from sqlalchemy import text

from plugins.osulib.models.score import OsuScore


def create_table():
    with bot.engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("CREATE TABLE IF NOT EXISTS osu_scores (id int, best_id int, user_id int, "
                                "beatmap_id int, accuracy float, mods byte, total_score int, "
                                "max_combo int, legacy_perfect bool, statistics byte, "
                                "passed bool, pp float, rank str, ended_at datetime, mode int, "
                                "replay bool, position int, weight byte)"))
        transaction.commit()


def insert_scores(query_data: list):
    with bot.engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("INSERT INTO osu_scores (id, best_id, user_id, beatmap_id, accuracy, mods, total_score, "
                 "max_combo, legacy_perfect, statistics, passed, pp, rank, ended_at, mode, replay, position, weight) "
                 "VALUES (:id, :best_id, :user_id, :beatmap_id, :accuracy, :mods, :total_score, "
                 ":max_combo, :legacy_perfect, :statistics, :passed, :pp, :rank, :ended_at, :mode, :replay, "
                 ":position, :weight)"),
            query_data
        )
        transaction.commit()


def delete_user_scores(user_id: int):
    with bot.engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("DELETE FROM osu_scores WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        transaction.commit()


def get_user_scores(user_id: int):
    with bot.engine.connect() as connection:
        result = connection.execute(
            text("SELECT * FROM osu_scores WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        score_list = []
        for osu_score in result.all():
            score_list.append(OsuScore(osu_score, db=True))
        return score_list
