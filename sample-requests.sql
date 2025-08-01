SELECT White, Black, Result, game_datetime, quality_score
FROM games
WHERE quality_score > 100
ORDER BY game_datetime ASC, quality_score DESC;

SELECT White, Black, Result, game_datetime, quality_score
FROM games
WHERE quality_score > 70
ORDER BY game_datetime ASC, quality_score DESC;

SELECT COUNT(*) FROM games WHERE quality_score > 70;

