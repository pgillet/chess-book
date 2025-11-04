import argparse
import chess.pgn
import chess.engine
import sys
import sqlite3
from datetime import datetime
import os
import math
import statistics
import bisect
from collections import defaultdict

# --- CONFIGURATION ---
ENGINE_PATH = "/opt/homebrew/bin/stockfish"

# --- DATABASE SCHEMA ---
DB_SCHEMA = {
    "Link": "TEXT PRIMARY KEY", "Event": "TEXT", "Site": "TEXT", "Date": "TEXT",
    "Round": "TEXT", "White": "TEXT", "Black": "TEXT", "Result": "TEXT",
    "WhiteElo": "INTEGER", "BlackElo": "INTEGER", "TimeControl": "TEXT",
    "Termination": "TEXT", "game_datetime": "TIMESTAMP", "winner": "TEXT",
    "num_moves": "INTEGER",
    "white_cpl": "REAL", "black_cpl": "REAL", # Ensure these are present
    "avg_cpl": "REAL", "cpl_std_dev": "REAL",
    "blunders": "INTEGER", "mistakes": "INTEGER", "quality_score": "REAL",
    "raw_pgn": "TEXT"
}


DEFAULT_SCORE_CONFIG = {
    # Base blend of interpretable components and contextual bonuses. We keep the
    # structure in a dict so the caller can override parts of the recipe without
    # editing the core function.
    'base_weight': 1.0,
    'sample_size': {
        # Dampen extreme scores when the move count is too small to be reliable.
        'baseline_moves': 40,
        'neutral_score': 0.45,
        'min_confidence': 0.05,
        'max_confidence': 1.0,
        'exponent': 1.0,
    },
    'components': {
        # `balance` tracks overall accuracy while penalising lopsided play.
        'balance': {'weight': 0.45, 'sharpness': 1.0, 'imbalance_penalty': 0.25},
        # Error rates are computed per 40 moves to normalise long tactical games.
        'blunders': {'weight': 0.2, 'sharpness': 1.1},
        'mistakes': {'weight': 0.15, 'sharpness': 1.1},
        # Consistency rewards low swing in the evaluation trajectory.
        'consistency': {'weight': 0.2, 'sharpness': 1.0},
    },
    'context': {
        # Length and precision bonuses sit outside the base weight so they simply
        # tip the scale when the cohort suggests a game is unusually long or clean.
        'length': {'weight': 0.2, 'sharpness': 1.0},
        'precision': {'weight': 0.1, 'sharpness': 1.0},
        # Checkmate and upset bonuses are gated to avoid inflating scrappy finishes.
        'checkmate': {'max_bonus': 0.05, 'min_balance_score': 0.55},
        'upset': {'max_bonus': 0.05, 'elo_threshold': 50, 'scale': 0.0005},
    },
}


# --- DATABASE FUNCTIONS ---


def compute_distribution_stats(values):
    # Capture summary statistics once so they can be reused across many games.
    # We record both classical (mean/std) and robust (median/MAD) measures plus the
    # sorted sequence for percentile lookups when the dispersion collapses.
    if not values:
        return {
            'mean': 0.0,
            'std': 0.0,
            'median': 0.0,
            'mad': 0.0,
            'sorted_values': [],
            'count': 0,
        }

    sorted_values = sorted(values)
    median = statistics.median(sorted_values)
    deviations = [abs(v - median) for v in sorted_values]
    mad = statistics.median(deviations) if deviations else 0.0
    std_dev = statistics.stdev(values) if len(values) > 1 else 0.0

    return {
        'mean': statistics.mean(values),
        'std': std_dev,
        'median': median,
        'mad': mad,
        'sorted_values': sorted_values,
        'count': len(values),
    }


def percentile_rank(sorted_values, value):
    # Bisect the sorted series so percentile queries are O(log n). We average the
    # left/right indexes to treat ties as occupying their full interval.
    if not sorted_values:
        return 0.5
    left = bisect.bisect_left(sorted_values, value)
    right = bisect.bisect_right(sorted_values, value)
    percentile = ((left + right) / 2) / len(sorted_values)
    return min(1.0, max(0.0, percentile))


def robust_z_score(value, distribution):
    # Prefer the classical z-score, but fall back to a MAD-based score and finally
    # an inverse-normal of the percentile when the cohort has near-zero spread.
    std_dev = distribution.get('std', 0.0)
    if std_dev and std_dev > 1e-9:
        return (value - distribution['mean']) / std_dev

    mad = distribution.get('mad', 0.0)
    if mad and mad > 1e-9:
        return (value - distribution['median']) / (mad * 1.4826)

    sorted_values = distribution.get('sorted_values') or []
    percentile = percentile_rank(sorted_values, value)
    epsilon = 1e-3
    percentile = min(1 - epsilon, max(epsilon, percentile))
    # Map percentile back to an approximate z-score for smoothness.
    return statistics.NormalDist().inv_cdf(percentile)


def score_from_z(z_value, sharpness=1.0):
    # Convert a z-score to a 0-1 logistic score so negative z (better than median)
    # pushes the result upward while accommodating configurable contrast.
    sharpness = max(1e-6, sharpness)
    return 1 / (1 + math.exp(z_value / sharpness))



def create_connection(db_file):
    """Create a database connection to the SQLite database specified by db_file"""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        print(e)
    return conn


def create_table(conn):
    """Create the games table using the DB_SCHEMA."""
    columns = ", ".join([f'"{col_name}" {col_type}' for col_name, col_type in DB_SCHEMA.items()])
    sql_create_table = f"CREATE TABLE IF NOT EXISTS games ({columns});"
    try:
        c = conn.cursor()
        c.execute(sql_create_table)
    except sqlite3.Error as e:
        print(e)


def insert_game_data(conn, game_data):
    """Insert a new game into the games table."""
    columns = ', '.join(game_data.keys())
    placeholders = ', '.join(['?' for _ in game_data])
    sql = f'INSERT OR REPLACE INTO games ({columns}) VALUES ({placeholders})'
    cur = conn.cursor()
    cur.execute(sql, list(game_data.values()))
    conn.commit()
    return cur.lastrowid


# --- ANALYSIS FUNCTIONS ---

def analyze_game(game, engine, username):
    """Analyzes a single game to extract metrics for both players."""
    analysis_data = {}
    white_cpls = []
    black_cpls = []

    board = game.board()
    moves = list(game.mainline_moves())

    if not moves:
        return None

    for move in moves:
        is_white_move = board.turn == chess.WHITE
        info = engine.analyse(board, chess.engine.Limit(depth=15))
        best_move_score = info.get("score").white()

        board.push(move)

        info_after = engine.analyse(board, chess.engine.Limit(depth=15))
        actual_move_score = info_after.get("score").white()

        if not best_move_score.is_mate() and not actual_move_score.is_mate():
            # CPL is the absolute difference in evaluation
            cpl = abs(best_move_score.score() - actual_move_score.score())
            if is_white_move:
                white_cpls.append(cpl)
            else:
                black_cpls.append(cpl)

    all_cpls = white_cpls + black_cpls
    if not all_cpls:
        return None

    analysis_data['num_moves'] = len(moves)
    analysis_data['white_cpl'] = statistics.mean(white_cpls) if white_cpls else 0
    analysis_data['black_cpl'] = statistics.mean(black_cpls) if black_cpls else 0
    analysis_data['avg_cpl'] = statistics.mean(all_cpls)
    analysis_data['cpl_std_dev'] = statistics.stdev(all_cpls) if len(all_cpls) > 1 else 0
    analysis_data['blunders'] = sum(1 for cpl in all_cpls if cpl >= 200)
    analysis_data['mistakes'] = sum(1 for cpl in all_cpls if 100 <= cpl < 200)

    return analysis_data


def calculate_comparative_score(metrics, stats, config=None):
    """
    Calculates a comparative quality score that rewards games outperforming the cohort
    across precision, consistency, and mistakes while preserving a smooth 0-100 scale.
    """

    config = config or DEFAULT_SCORE_CONFIG
    components_cfg = config.get('components', {})
    context_cfg = config.get('context', {})
    base_weight = config.get('base_weight', 1.0)

    # Error counts are normalised by a 40-move slice so marathon struggles do not
    # automatically accumulate more blunders/mistakes than sprints.
    moves_scale = max(metrics['num_moves'], 1) / 40.0
    blunders_rate = metrics['blunders'] / moves_scale
    mistakes_rate = metrics['mistakes'] / moves_scale

    # Treat balance as a blend of both sides' accuracy and explicitly penalise
    # imbalanced games using the config-supplied multiplier.
    white_cpl_z = robust_z_score(metrics['white_cpl'], stats['white_cpl'])
    black_cpl_z = robust_z_score(metrics['black_cpl'], stats['black_cpl'])
    imbalance_penalty = components_cfg.get('balance', {}).get('imbalance_penalty', 0.0)
    balance_z = (white_cpl_z + black_cpl_z) / 2 + imbalance_penalty * abs(white_cpl_z - black_cpl_z)

    # Feed the normalised error and volatility measures through the same pathway.
    blunders_z = robust_z_score(blunders_rate, stats['blunders_per_40'])
    mistakes_z = robust_z_score(mistakes_rate, stats['mistakes_per_40'])
    cpl_std_dev_z = robust_z_score(metrics['cpl_std_dev'], stats['cpl_std_dev'])

    component_inputs = {
        'balance': balance_z,
        'blunders': blunders_z,
        'mistakes': mistakes_z,
        'consistency': cpl_std_dev_z,
    }

    base_score_weighted = 0.0
    component_weight_total = 0.0
    component_scores = {}

    # Weighted logistic combination of the base components. Every weight is
    # normalised so altering the config keeps the result in a predictable range.
    for key, z_value in component_inputs.items():
        cfg = components_cfg.get(key, {})
        weight = cfg.get('weight', 0.0)
        if weight <= 0:
            continue
        component_score = score_from_z(z_value, cfg.get('sharpness', 1.0))
        component_scores[key] = component_score
        base_score_weighted += weight * component_score
        component_weight_total += weight

    base_score = base_score_weighted / component_weight_total if component_weight_total else 0.0

    context_total = 0.0
    context_weight_total = 0.0

    # Contextual adjustments start here. These sit outside the base weight so they
    # act like incremental nudges rather than rewriting the component balance.
    length_cfg = context_cfg.get('length')
    if length_cfg and stats['num_moves']['count'] > 0:
        # A long game that outlasts the cohort should get a small lift, achieved by
        # inverting the z-score so higher-than-average move counts yield better scores.
        length_z = robust_z_score(metrics['num_moves'], stats['num_moves'])
        length_score = score_from_z(-length_z, length_cfg.get('sharpness', 1.0))
        context_total += length_score * length_cfg.get('weight', 0.0)
        context_weight_total += length_cfg.get('weight', 0.0)

    precision_cfg = context_cfg.get('precision')
    precision_score = None
    if precision_cfg and stats['avg_cpl']['count'] > 0:
        # Combine the overall average CPL with the winner's CPL (when available) to
        # emphasise clean victories where both figures rate higher than the cohort.
        avg_precision = score_from_z(
            robust_z_score(metrics['avg_cpl'], stats['avg_cpl']),
            precision_cfg.get('sharpness', 1.0)
        )
        precision_components = [avg_precision]

        winner_side = metrics.get('winner_side')
        winner_cpl = None
        winner_distribution = None
        if winner_side == 'white':
            winner_cpl = metrics['white_cpl']
            winner_distribution = stats['white_cpl']
        elif winner_side == 'black':
            winner_cpl = metrics['black_cpl']
            winner_distribution = stats['black_cpl']

        if winner_cpl is not None and winner_distribution and winner_distribution['count'] > 0:
            winner_precision = score_from_z(
                robust_z_score(winner_cpl, winner_distribution),
                precision_cfg.get('sharpness', 1.0)
            )
            precision_components.append(winner_precision)

        precision_score = sum(precision_components) / len(precision_components)
        context_total += precision_score * precision_cfg.get('weight', 0.0)
        context_weight_total += precision_cfg.get('weight', 0.0)

    # Blend base and context contributions into a 0-1 value before additive bonuses.
    total_weight = base_weight + context_weight_total if (base_weight + context_weight_total) > 0 else 1.0
    combined_score = (base_score * base_weight + context_total) / total_weight

    termination_text = (metrics.get('Termination') or "").lower()
    checkmate_cfg = context_cfg.get('checkmate', {})
    if "checkmate" in termination_text and checkmate_cfg:
        # Require the checkmating side to have delivered a balanced, precise game; a
        # scrappy swindle should not get the same boost as a model mate.
        balance_component = component_scores.get('balance', 0.0)
        min_balance = checkmate_cfg.get('min_balance_score', 0.0)
        balance_factor = 0.0
        if balance_component > min_balance:
            balance_factor = (balance_component - min_balance) / max(1e-6, 1 - min_balance)

        precision_factor = 0.0
        if precision_score is not None:
            precision_factor = max(0.0, precision_score - 0.5) * 2

        if balance_factor > 0 and precision_factor > 0:
            checkmate_bonus = checkmate_cfg.get('max_bonus', 0.0) * min(1.0, (balance_factor + precision_factor) / 2)
            combined_score += checkmate_bonus

    upset_cfg = context_cfg.get('upset', {})
    winner_elo = metrics.get('winner_elo', 0)
    loser_elo = metrics.get('loser_elo', 0)
    if upset_cfg and winner_elo and loser_elo and winner_elo > 0 and loser_elo > 0:
        elo_diff = loser_elo - winner_elo
        # Reward meaningful upsets scaled by the Elo gap, clamped to the configured
        # ceiling so huge rating differences do not dominate the scale.
        if elo_diff > upset_cfg.get('elo_threshold', 0):
            upset_bonus = min(upset_cfg.get('max_bonus', 0.0), elo_diff * upset_cfg.get('scale', 0.0))
            combined_score += upset_bonus

    combined_score = max(0.0, min(1.0, combined_score))

    sample_cfg = config.get('sample_size', {})
    baseline_moves = float(sample_cfg.get('baseline_moves', 0))
    if baseline_moves > 0:
        min_conf = max(0.0, min(1.0, float(sample_cfg.get('min_confidence', 0.0))))
        max_conf = max(min_conf, min(1.0, float(sample_cfg.get('max_confidence', 1.0))))
        exponent = float(sample_cfg.get('exponent', 1.0))
        exponent = max(1e-6, exponent)

        raw_conf = metrics.get('num_moves', 0) / baseline_moves
        raw_conf = max(min_conf, min(max_conf, raw_conf))
        confidence = raw_conf ** exponent

        neutral_score = float(sample_cfg.get('neutral_score', 0.5))
        combined_score = neutral_score + confidence * (combined_score - neutral_score)
        combined_score = max(0.0, min(1.0, combined_score))

    return combined_score * 100


# --- MAIN SCRIPT FUNCTIONS ---

def build_database(input_pgn, db_file, group_by_time_control=False):
    """
    Builds the database in two passes to calculate comparative scores.
    """
    if os.path.exists(db_file):
        os.remove(db_file)

    conn = create_connection(db_file)
    create_table(conn)

    engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
    engine.configure({"Threads": 1, "Hash": 128})

    username = None
    game_count = 0

    print("--- PASS 1: Analyzing games and collecting raw metrics ---")
    with open(input_pgn) as pgn:
        while True:
            game = chess.pgn.read_game(pgn)
            if game is None: break
            game_count += 1
            if username is None: username = game.headers.get("White")
            print(f"Analyzing game {game_count}...")

            analysis_metrics = analyze_game(game, engine, username)
            if not analysis_metrics: continue

            # --- CORRECTED LOGIC ---
            # This now filters the game headers to only include keys
            # that are defined in our DB_SCHEMA, preventing errors.
            game_data = {}
            for key in DB_SCHEMA.keys():
                if key in game.headers:
                    game_data[key] = game.headers[key]
                elif key in analysis_metrics:
                    game_data[key] = analysis_metrics[key]
                elif key == "game_datetime":
                    try:
                        utc_date = game.headers.get("UTCDate", "1970.01.01")
                        utc_time = game.headers.get("UTCTime", "00:00:00")
                        game_datetime = datetime.strptime(
                            f"{utc_date} {utc_time}", "%Y.%m.%d %H:%M:%S"
                        )
                        game_data[key] = game_datetime.isoformat(sep=" ")
                    except ValueError:
                        game_data[key] = None

            game_data["raw_pgn"] = str(game)
            # Ensure integer fields are correctly typed
            for key in ["WhiteElo", "BlackElo"]:
                if key in game_data and game_data[key] != "?":
                    game_data[key] = int(game_data[key])
                else:
                    game_data[key] = 0

            insert_game_data(conn, game_data)

    print(f"\n--- PASS 2: Calculating comparative quality scores ---")

    cur = conn.cursor()
    cur.execute(
        "SELECT Link, white_cpl, black_cpl, blunders, mistakes, cpl_std_dev, num_moves, White, Black, Result, Termination, TimeControl, avg_cpl, WhiteElo, BlackElo FROM games")
    all_games_data = cur.fetchall()

    if not all_games_data:
        print("No games were analyzed. Exiting.")
        return

    groups = defaultdict(list)
    for row in all_games_data:
        key = row[11] if group_by_time_control else 'all'
        groups[key].append(row)

    for group_key, group_games in groups.items():
        print(f"Calculating scores for group: '{group_key}' ({len(group_games)} games)")

        # Collect raw values for each metric so we can produce cohort statistics
        # once per group instead of recalculating them for every game.
        metric_lists = {
            'white_cpl': [],
            'black_cpl': [],
            'blunders_per_40': [],
            'mistakes_per_40': [],
            'cpl_std_dev': [],
            'num_moves': [],
            'avg_cpl': [],
        }

        for game_data in group_games:
            # Unpack the fields and coerce any NULLs into neutral zeros before
            # computing rates. This keeps later calculations straightforward.
            white_cpl = game_data[1] or 0.0
            black_cpl = game_data[2] or 0.0
            blunders = game_data[3] or 0.0
            mistakes = game_data[4] or 0.0
            cpl_std_dev = game_data[5] or 0.0
            num_moves = game_data[6] or 0
            avg_cpl = game_data[12] or 0.0

            moves_scale = max(num_moves, 1) / 40.0
            blunders_per_40 = blunders / moves_scale
            mistakes_per_40 = mistakes / moves_scale

            metric_lists['white_cpl'].append(white_cpl)
            metric_lists['black_cpl'].append(black_cpl)
            metric_lists['blunders_per_40'].append(blunders_per_40)
            metric_lists['mistakes_per_40'].append(mistakes_per_40)
            metric_lists['cpl_std_dev'].append(cpl_std_dev)
            metric_lists['num_moves'].append(num_moves)
            metric_lists['avg_cpl'].append(avg_cpl)

        stats = {key: compute_distribution_stats(values) for key, values in metric_lists.items()}

        for game_data in group_games:
            (
                link,
                white_cpl,
                black_cpl,
                blunders,
                mistakes,
                cpl_std_dev,
                num_moves,
                white,
                black,
                result,
                termination,
                _,
                avg_cpl,
                white_elo,
                black_elo,
            ) = game_data

            white_cpl = white_cpl or 0.0
            black_cpl = black_cpl or 0.0
            blunders = blunders or 0.0
            mistakes = mistakes or 0.0
            cpl_std_dev = cpl_std_dev or 0.0
            num_moves = num_moves or 0
            avg_cpl = avg_cpl or 0.0
            white_elo = white_elo or 0
            black_elo = black_elo or 0

            winner = ""
            winner_side = None
            if result == "1-0":
                winner = white
                winner_side = 'white'
            elif result == "0-1":
                winner = black
                winner_side = 'black'

            winner_elo = 0
            loser_elo = 0
            if winner_side == 'white':
                winner_elo = white_elo
                loser_elo = black_elo
            elif winner_side == 'black':
                winner_elo = black_elo
                loser_elo = white_elo

            metrics = {
                # All core metrics needed by the scoring function, plus contextual
                # data for the optional bonuses.
                'white_cpl': white_cpl,
                'black_cpl': black_cpl,
                'avg_cpl': avg_cpl,
                'blunders': blunders,
                'mistakes': mistakes,
                'cpl_std_dev': cpl_std_dev,
                'num_moves': num_moves,
                'winner': winner,
                'winner_side': winner_side,
                'Termination': termination,
                'winner_elo': winner_elo,
                'loser_elo': loser_elo,
            }

            score = calculate_comparative_score(metrics, stats, DEFAULT_SCORE_CONFIG)
            cur.execute("UPDATE games SET quality_score = ? WHERE Link = ?", (score, link))

    conn.commit()
    conn.close()
    engine.quit()
    print(f"\n✅ Database '{db_file}' built and scored successfully.")


def export_top_games(db_file, output_pgn, top_n, sort_by, min_score, max_score):
    """Exports the top N games based on the selected sorting criteria."""
    conn = create_connection(db_file)
    cur = conn.cursor()

    order_clauses = []
    for s in sort_by:
        parts = s.split(':')
        col = parts[0]
        direction = parts[1].upper() if len(parts) > 1 and parts[1].lower() in ['asc', 'desc'] else 'DESC'
        order_clauses.append(f"{col} {direction}")

    query = f"SELECT raw_pgn FROM games"

    where_clauses = []
    params = []
    if min_score is not None:
        where_clauses.append("quality_score >= ?")
        params.append(min_score)
    if max_score is not None:
        where_clauses.append("quality_score <= ?")
        params.append(max_score)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += f" ORDER BY {', '.join(order_clauses)} LIMIT ?"
    params.append(top_n)

    cur.execute(query, params)

    rows = cur.fetchall()

    with open(output_pgn, 'w') as f:
        for row in rows:
            f.write(row[0] + "\n\n")

    conn.close()
    print(f"✅ Exported {len(rows)} games to '{output_pgn}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze and select top chess games from a PGN file.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Build Command ---
    parser_build = subparsers.add_parser("build", help="Build and populate the analysis database from a PGN file.")
    parser_build.add_argument("input_pgn", type=str, help="Path to the input PGN file.")
    parser_build.add_argument("db_file", type=str, help="Path to the SQLite database file to create.")
    parser_build.add_argument(
        "--group_by_time_control",
        action="store_true",
        help="Normalize and rank games separately within each time control group."
    )

    # --- Export Command ---
    parser_export = subparsers.add_parser("export", help="Export the top N games from the database to a new PGN file.")
    parser_export.add_argument("db_file", type=str, help="Path to the existing SQLite database file.")
    parser_export.add_argument("output_pgn", type=str, help="Path for the output PGN file.")
    parser_export.add_argument("-n", "--top_n", type=int, default=50,
                               help="Number of top games to export (default: 50).")
    parser_export.add_argument(
        "--sort_by",
        nargs='+',
        default=["quality_score:desc"],
        help="Sort order for games, e.g., 'quality_score:desc' 'game_datetime:asc' (default: 'quality_score:desc')."
    )
    parser_export.add_argument("--min_score", type=float, help="Optional: minimum quality score for exported games.")
    parser_export.add_argument("--max_score", type=float, help="Optional: maximum quality score for exported games.")

    args = parser.parse_args()

    if args.command == "build":
        build_database(args.input_pgn, args.db_file, args.group_by_time_control)
    elif args.command == "export":
        export_top_games(args.db_file, args.output_pgn, args.top_n, args.sort_by, args.min_score, args.max_score)
