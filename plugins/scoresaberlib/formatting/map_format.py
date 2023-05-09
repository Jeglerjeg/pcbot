def format_beatmap_difficulty(difficulty: int):
    formatted_diff = ""
    if difficulty == 1:
        formatted_diff = "Easy"
    elif difficulty == 3:
        formatted_diff = "Normal"
    elif difficulty == 5:
        formatted_diff = "Hard"
    elif difficulty == 7:
        formatted_diff = "Expert"
    elif difficulty == 9:
        formatted_diff = "Expert+"
    return formatted_diff