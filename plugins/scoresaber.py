import discord
import bot
import plugins
from pcbot import utils, Annotate

from plugins.scoresaberlib import api, db
from plugins.scoresaberlib.formatting import score_format, embed_format
from plugins.scoresaberlib.tracking import ScoreSaberTracker
from plugins.scoresaberlib.utils import user_utils, score_utils, misc_utils
from plugins.scoresaberlib.config import scoresaber_config

client = plugins.client  # type: bot.Client

scoresaber_tracker = ScoreSaberTracker()


@plugins.command()
async def scoresaber(message, _: utils.placeholder):
    """ Score saber plugin. """

@scoresaber.command(aliases="set")
async def link(message: discord.Message, name: Annotate.LowerContent):
    """ Tell the bot who you are on scoresaber!. """
    scoresaber_user = await api.get_user(name)

    # Check if the scoresaber! user exists
    assert scoresaber_user, f"scoresaber user `{name}` does not exist."

    # Assign the user using their unique user_id
    if db.get_linked_scoresaber_profile(message.author.id):
        db.delete_linked_scoresaber_profile(message.author.id)
    db.insert_linked_scoresaber_profile(message.author.id, scoresaber_user.id, message.guild.id)

    await client.say(message, f"Set your scoresaber profile to `{scoresaber_user.name}`.")

@scoresaber.command(aliases="unset")
async def unlink(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Unlink your scoresaber! account or unlink the member specified (**Owner only**). """
    # The message author is allowed to unlink himself
    # If a member is specified and the member is not the owner, set member to the author
    if not plugins.is_owner(message.author):
        member = message.author

    # The member might not be linked to any profile
    assert db.get_linked_scoresaber_profile(member.id), user_utils.get_missing_user_string(member)

    # Unlink the given member (usually the message author)
    db.delete_linked_scoresaber_profile(member.id)
    await client.say(message, f"Unlinked **{member.name}'s** scoresaber profile.")


@scoresaber.command()
async def score(message: discord.Message, map_id: int, user: str = None):
    if not user:
        user = message.author.mention
    scoresaber_user = await user_utils.get_user(message, user)
    assert scoresaber_user, "Couldn't find user."
    scoresaber_score = await api.get_user_map_score(map_id, scoresaber_user.name)
    leaderboard_info = await api.get_leaderboard_info(map_id)
    formatted_text = score_format.format_new_score(scoresaber_score, leaderboard_info)
    embed = embed_format.get_embed_from_template(formatted_text,
                                                 message.author.color,
                                                 scoresaber_user.name,
                                                 user_utils.get_user_url(scoresaber_user.id),
                                                 scoresaber_user.profile_picture,
                                                 leaderboard_info.cover_image)
    await client.send_message(message.channel, embed=embed)

@scoresaber.command()
async def recent(message: discord.Message, user: str = None):
    if not user:
        user = message.author.mention
    scoresaber_user = await user_utils.get_user(message, user)
    assert scoresaber_user, "Couldn't find user."
    scoresaber_scores = await api.get_user_scores(scoresaber_user.id, "recent", 1)
    if not scoresaber_scores or len(scoresaber_scores) <1:
        await client.say(message, "Found no recent score.")
        return
    recent_score = scoresaber_scores[0]
    scoresaber_score = recent_score[0]
    leaderboard_info = recent_score[1]
    formatted_text = score_format.format_new_score(scoresaber_score, leaderboard_info, scoresaber_score.rank)
    embed = embed_format.get_embed_from_template(formatted_text,
                                                 message.author.color,
                                                 scoresaber_user.name,
                                                 user_utils.get_user_url(scoresaber_user.id),
                                                 scoresaber_user.profile_picture,
                                                 leaderboard_info.cover_image)
    await client.send_message(message.channel, embed=embed)

@scoresaber.command(name="top")
async def top(message: discord.Message, user: str = None):
    """ By default displays your or the selected member's 5 highest rated plays sorted by PP.
     You can also add "nochoke" as an option to display a list of unchoked top scores instead.
     Alternative sorting methods are "oldest", "newest", "combo", "score" and "acc" """

    if not user:
        user = message.author.mention
    scoresaber_user = await user_utils.get_user(message, user)
    assert scoresaber_user, "Couldn't find user."

    fetched_scores = await api.get_user_scores(scoresaber_user.id, "top", 100)
    assert fetched_scores, "Failed to retrieve scores. Please try again."
    for i, scoresaber_score in enumerate(fetched_scores):
        scoresaber_score[0].add_position(i + 1)

    m = await score_format.get_formatted_score_list(fetched_scores, 5)
    e = embed_format.get_embed_from_template(m, message.author.color, scoresaber_user.name,
                                             user_utils.get_user_url(scoresaber_user.id),
                                             scoresaber_user.profile_picture,
                                             scoresaber_user.profile_picture)
    view = score_format.PaginatedScoreList(fetched_scores,
                                           score_utils.count_score_pages(fetched_scores, 5), e)
    e.set_footer(text=f"Page {1} of {score_utils.count_score_pages(fetched_scores, 5)}")
    message = await client.send_message(message.channel, embed=e, view=view)
    await view.wait()
    await message.edit(embed=view.embed, view=None)

@scoresaber.command(aliases="configure cfg")
async def config(message, _: utils.placeholder):
    """ Manage configuration for this plugin. """


@config.command(name="scores", alias="score", permissions="manage_guild")
async def config_scores(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post scores to. """
    await misc_utils.init_guild_config(message.guild)
    scoresaber_config.data["guild"][str(message.guild.id)]["score-channels"] = list(str(c.id) for c in channels)
    await scoresaber_config.asyncsave()
    await client.say(message, f"**Notifying scores in**: {utils.format_objects(*channels, sep=' ') or 'no channels'}")

@scoresaber.command(owner=True)
async def debug(message: discord.Message):
    """ Display some debug info. """
    client_time = f"<t:{int(client.time_started.timestamp())}:F>"
    linked_profiles = db.get_linked_scoresaber_profiles()
    tracked_profiles = db.get_scoresaber_users()
    member_list = []
    for linked_profile in linked_profiles:
        if any(linked_profile.scoresaber_id == scoresaber_user.id for scoresaber_user in tracked_profiles):
            member = discord.utils.get(client.get_all_members(), id=linked_profile.id)
            if member and user_utils.is_playing(member):
                member_list.append(f"`{member.name}`")

    average_requests = utils.format_number(api.requests_sent /
                                           ((discord.utils.utcnow() - client.time_started).total_seconds() / 60.0), 2) \
        if api.requests_sent > 0 else 0
    last_update = f"<t:{int(scoresaber_tracker.previous_update.timestamp())}:F>" \
        if scoresaber_tracker.previous_update else "Not updated yet."
    await client.say(message, f"Sent `{api.requests_sent}` requests since the bot started ({client_time}).\n"
                              f"Sent an average of `{average_requests}` requests per minute. \n"
                              f"Spent `{scoresaber_tracker.time_elapsed:.3f}` seconds last update.\n"
                              f"Last update happened at: {last_update}\n"
                              f"Members registered as playing: {', '.join(member_list) if member_list else 'None'}\n"
                              f"Total members tracked: `{len(tracked_profiles)}`")