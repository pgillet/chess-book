WITH ranked_games AS (
    SELECT
        TimeControl,
        Link,
        game_datetime,
        White,
        Black,
        Result,
        white_cpl,
        black_cpl,
        quality_score,
        raw_pgn,
        ROW_NUMBER() OVER (
            PARTITION BY TimeControl
            ORDER BY quality_score DESC
        ) AS rank_in_group
    FROM games
)
SELECT
    TimeControl,
    game_datetime,
    Link,
    White,
    Black,
    Result,
    white_cpl,
    black_cpl,
    quality_score
    --concat(raw_pgn, CHAR(13), CHAR(10))
FROM ranked_games
WHERE rank_in_group <= 5 -- AND quality_score >= 60.0
    AND (
        (TimeControl = '1/259200' AND quality_score >= 60.0) OR
        (TimeControl = '1/86400' AND quality_score >= 70.0) OR
        (TimeControl = '120+1' AND quality_score >= 60.0) OR
        (TimeControl = '180' AND quality_score >= 70.0) OR
        (TimeControl = '180+2' AND quality_score >= 75.0) OR
        (TimeControl = '1800' AND quality_score >= 60.0) OR
        (TimeControl = '300' AND quality_score >= 67.0) OR
        (TimeControl = '60+1' AND quality_score >= 75.0) OR
        (TimeControl = '600' AND quality_score >= 65.0)
    )
ORDER BY TimeControl ASC;
