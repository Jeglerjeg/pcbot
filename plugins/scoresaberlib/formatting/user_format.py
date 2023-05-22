from pcbot import utils
from plugins.scoresaberlib.models.player import ScoreSaberPlayer


def format_user_diff(new_scoresaber_user: ScoreSaberPlayer, old_scoresaber_user: ScoreSaberPlayer):
    """ Get a bunch of differences and return a formatted string to send.
    iso is the country code. """
    pp_rank = new_scoresaber_user.rank
    pp_country_rank = new_scoresaber_user.country_rank
    iso = new_scoresaber_user.country
    rank = -(new_scoresaber_user.rank - old_scoresaber_user.rank)
    country_rank = -(new_scoresaber_user.country_rank - old_scoresaber_user.country_rank)
    accuracy = new_scoresaber_user.score_stats.average_ranked_accuracy - old_scoresaber_user.score_stats.average_ranked_accuracy
    pp_diff = new_scoresaber_user.pp - old_scoresaber_user.pp
    ranked_score = new_scoresaber_user.score_stats.total_ranked_score - old_scoresaber_user.score_stats.total_ranked_score
    rankings_url = f"https://scoresaber.com/rankings/"

    # Find the performance page number of the respective ranks

    formatted = [f"`{utils.format_number(new_scoresaber_user.pp, 2)}pp "
                 f"{utils.format_number(pp_diff, 2):+}pp`",
                 f" [\U0001f30d]({rankings_url}?page="
                 f"{pp_rank // 50 + 1})`#{pp_rank:,}{'' if int(rank) == 0 else f' {int(rank):+}'}`",
                 f" [{utils.text_to_emoji(iso)}]({rankings_url}?countries={iso}&page="
                 f"{pp_country_rank // 50 + 1})`"
                 f"#{pp_country_rank:,}{'' if int(country_rank) == 0 else f' {int(country_rank):+}'}`"]
    rounded_acc = utils.format_number(accuracy, 3)
    if rounded_acc > 0:
        formatted.append("\n\U0001f4c8")  # Graph with upwards trend
    elif rounded_acc < 0:
        formatted.append("\n\U0001f4c9")  # Graph with downwards trend
    else:
        formatted.append("\n\U0001f3af")  # Dart

    formatted.append(f"`{utils.format_number(new_scoresaber_user.score_stats.average_ranked_accuracy, 3)}%"
                     f"{'' if rounded_acc == 0 else f' {rounded_acc:+}%'}`")

    formatted.append(f' \U0001f522`{new_scoresaber_user.score_stats.total_ranked_score:,}'
                     f'{"" if ranked_score == 0 else f" {int(ranked_score):+,}"}`')

    return "".join(formatted)