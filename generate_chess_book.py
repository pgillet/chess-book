import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent
import argparse
import shutil  # For deleting directories
import subprocess  # For running pdflatex

import chess.engine
import chess.pgn

LATEX_COMPILE_PASSES = 2
ENGINE_PATH = "/opt/homebrew/bin/stockfish"  # Update if necessary
TWO_COLUMN_THRESHOLD = 25  # Number of full moves to trigger two-column layout

# Defines all paper, font, margin, and board size settings.
PAPER_SIZE_SETTINGS = {
    'a5': {'paper': 'a5paper', 'font': '10pt', 'inner': '18mm', 'outer': '12mm', 'top': '20mm', 'bottom': '20mm', 'board_size': '16pt'},
    'a4': {'paper': 'a4paper', 'font': '11pt', 'inner': '25mm', 'outer': '20mm', 'top': '20mm', 'bottom': '20mm', 'board_size': '20pt'},
    'a3': {'paper': 'a3paper', 'font': '12pt', 'inner': '30mm', 'outer': '25mm', 'top': '20mm', 'bottom': '20mm', 'board_size': '24pt'},
}

INLINE_CHESS_SYMBOL = {
    'P': r'\WhitePawnOnWhite', 'N': r'\WhiteKnightOnWhite', 'B': r'\WhiteBishopOnWhite',
    'R': r'\WhiteRookOnWhite', 'Q': r'\WhiteQueenOnWhite', 'K': r'\WhiteKingOnWhite',
    'p': r'\BlackPawnOnWhite', 'n': r'\BlackKnightOnWhite', 'b': r'\BlackBishopOnWhite',
    'r': r'\BlackRookOnWhite', 'q': r'\BlackQueenOnWhite', 'k': r'\BlackKingOnWhite',
}

UNICODE_CHESS_SYMBOL = {
    'P': r'\usym{2659}', 'N': r'\usym{2658}', 'B': r'\usym{2657}',
    'R': r'\usym{2656}', 'Q': r'\usym{2655}', 'K': r'\usym{2654}',
    'p': r'\usym{265F}', 'n': r'\usym{265E}', 'b': r'\usym{265D}',
    'r': r'\usym{265C}', 'q': r'\usym{265B}', 'k': r'\usym{265A}',
}


def get_latex_header_part1(settings):
    """
    Generates the LaTeX header dynamically based on the chosen paper and margin settings.
    """
    documentclass_options = f"{settings['paper']},{settings['font']}"
    geometry_options = f"inner={settings['inner']},outer={settings['outer']},top={settings['top']},bottom={settings['bottom']}"

    return dedent(fr'''
        \documentclass[{documentclass_options}]{{book}}
        \usepackage[{geometry_options}]{{geometry}}
        \usepackage{{graphicx}}
        \usepackage{{chessboard}}
        \usepackage{{multicol}}
        \usepackage{{fancyhdr}}
        \usepackage{{titlesec}}
        \usepackage{{parskip}}
        \usepackage{{tabularx}}
        \usepackage{{longtable}}
        \usepackage{{skak}}
        \usepackage{{scalerel}}
        \usepackage{{array}} % Required for >{{\centering\arraybackslash}}
        \usepackage{{amssymb}} % For \Box, \blacksquare, and \star symbols
        \usepackage{{enumitem}}
        \usepackage{{calc}}
        \usepackage{{xcolor}}
        \usepackage{{tikz}}
        \usepackage[T1]{{fontenc}}
        \usepackage{{helvet}}

        \definecolor{{ChesscomGreen}}{{RGB}}{{78, 120, 55}}

        \renewcommand{{\tabularxcolumn}}[1]{{>{{\centering\arraybackslash}}m{{#1}}}}

        % --- Styling for all section-level titles ---
        \titleformat{{\section}}{{\normalfont\Large\bfseries}}{{}}{{0pt}}{{}}
        \titlespacing*{{\section}}{{0pt}}{{1.5ex}}{{1ex}}
        \titlespacing*{{\subsection}}{{0pt}}{{1.5ex}}{{1ex}}
        \titlespacing*{{\subsubsection}}{{0pt}}{{1.5ex}}{{1ex}}

        % tocsetup is now much simpler
        \setcounter{{secnumdepth}}{{-1}}
        \setcounter{{tocdepth}}{{1}}
        \setlength{{\parindent}}{{0pt}}

        % Only need to define the header for right-hand pages (for sections)
        \renewcommand{{\sectionmark}}[1]{{\markright{{#1}}}}

        \pagestyle{{fancy}}
        \fancyhf{{}}
        \renewcommand{{\headrulewidth}}{{0pt}}

        \fancyhead[RO]{{\nouppercase{{\rightmark}}}}
        \fancyfoot[LE,RO]{{\thepage}}

        \fancypagestyle{{plain}}{{
            \fancyhf{{}}
            \fancyfoot[LE,RO]{{\thepage}}
            \renewcommand{{\headrulewidth}}{{0pt}}
        }}
        \begin{{document}}
    ''')


LATEX_HEADER_PART2_TOC = dedent(r'''
    \tableofcontents % Generates the Table of Contents
''')

LATEX_FOOTER = "\\end{document}"

MESSAGES = {
    'en': {
        'game_event_default': 'Game',
        'white_player_default': 'White',
        'black_player_default': 'Black',
        'analysis_summary_title': 'Analysis Summary',
        'overall_accuracy': 'Overall Accuracy:',
        'white_avg_cpl': 'White Average CPL:',
        'black_avg_cpl': 'Black Average CPL:',
        'mistakes_blunders': 'Mistakes & Blunders:',
        'blunders_text': 'Blunders',
        'blunder_text_singular': 'Blunder',
        'mistakes_text': 'Mistakes',
        'mistake_text_singular': 'Mistake',
        'inaccuracies_text': 'Inaccuracies',
        'inaccuracy_text_singular': 'Inaccuracy',
        'good_move_text': 'Good Move',
        'eval_text': 'Eval:',
        'best_move_text': 'Best:',
        'loss_text': 'Loss:',
        'cp_text': 'cp',
        'best_move_played_text': 'Best Move',
        'error_starting_stockfish': "Error starting Stockfish engine: {e}. Please ensure '{ENGINE_PATH}' is correct and Stockfish is installed.",
        'analysis_disabled_warning': "Analysis features (CPL, blunders, best moves) will be disabled for all games.",
        'skipping_stockfish_analysis': "Skipping Stockfish analysis for game {game_num} due to engine error.",
        'exporting_game': "Exporting game {current_game}/{total_games} to LaTeX...",
        'skipping_game_error': "⚠️ Skipping game {game_num} due to an error during processing: {error_msg}",
        'deleting_output_dir': "Deleting existing output directory: {output_dir}",
        'error_deleting_dir': "Error deleting directory {output_dir}: {error_msg}",
        'compiling_latex': "Compiling LaTeX files in {output_dir}...",
        'main_latex_not_found': "Main LaTeX file not found: {main_tex_file}",
        'latex_compile_failed': "LaTeX compilation failed on pass {pass_num}. Output:",
        'pdflatex_not_found': "Error: pdflatex command not found. Please ensure LaTeX is installed and in your PATH.",
        'unexpected_latex_error': "An unexpected error occurred during LaTeX compilation: {error_msg}",
        'latex_compile_complete': "LaTeX compilation complete. Cleaning up auxiliary files...",
        'front_matter_page_file_not_found': "Warning: file not found at {path}",
        'error_reading_front_matter_page': "Warning: Could not read file {path}: {e}",
        'date_format': "%B %d, %Y",
        'months': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
                   'November', 'December'],
        'fn_white_player': 'The white square denotes the player with the White pieces.',
        'fn_black_player': 'The black square denotes the player with the Black pieces.',
        'fn_winner': 'A star symbol appears next to the winner of the game.',
        'fn_date': 'The date the game was played.',
        'fn_event': 'The event or tournament name.',
        'fn_time_control': 'The time control for the game (e.g., 60+1 means 60 seconds base time with a 1-second increment per move).',
        'fn_notation_algebraic': 'The game moves are listed in Standard Algebraic Notation.',
        'fn_notation_figurine': 'The game moves are listed in figurine notation, where a symbol represents each piece.',
        'fn_analysis_summary': 'A summary of the computer analysis, including average centipawn loss (CPL) for each player. Lower CPL is better.',
        'fn_board_diagram_all': 'Board diagrams are shown for every move pair. The board on the left shows the position after White\'s move, and the board on the right shows the position after Black\'s response. The start and end squares of each move are highlighted. A circled king is in check; a circled king with a cross is in checkmate.',
        'fn_board_diagram_smart': 'Board diagrams are only shown for "smart" move pairs, where at least one move was interesting. The board on the left shows the position after White\'s move, and the board on the right is after Black\'s response. The start and end squares of each move are highlighted. A circled king is in check; a circled king with a cross is in checkmate.',
        'fn_move_reminder': 'This title shows the move pair in Standard Algebraic Notation.',
        'fn_analysis_explanation': 'Evaluation is always from White\'s perspective: a positive value indicates a White advantage, a negative value a Black advantage. The score is either a numerical value expressed in centipawns (1/100th of a pawn), or a string like MX (Mate in X moves). For example, a score of +1.50c means White is ahead by 1.5 centipawns, while -M3 means Black has a forced checkmate in 3 moves. | Loss: The centipawn loss for the move played compared to the engine\'s best move. (Good Move, Mistake, Blunder): A classification of the move based on the centipawn loss. Best: The engine\'s preferred move if it differs from the one played.',
        'how_to_read_title': 'How to Read This Book',
        'table_metric': 'Metric',
        'table_white': 'White',
        'table_black': 'Black',
        'table_avg_cpl': 'Average CPL',
        'table_blunders': 'Blunders',
        'table_mistakes': 'Mistakes',
        'table_inaccuracies': 'Inaccuracies',
        'term_agreement': 'Game drawn by agreement',
        'term_repetition': 'Game drawn by repetition',
        'term_stalemate': 'Game drawn by stalemate',
        'term_timeout_vs_insufficient': 'Game drawn by timeout vs insufficient material',
        'term_abandoned': '{player} won - game abandoned',
        'term_checkmate': '{player} won by checkmate',
        'term_resignation': '{player} won by resignation',
        'term_time': '{player} won on time',
        'toc_title': 'Table of Contents',
    },
    'fr': {
        'game_event_default': 'Partie',
        'white_player_default': 'Blanc',
        'black_player_default': 'Noir',
        'analysis_summary_title': 'Résumé de l\'Analyse',
        'overall_accuracy': 'Précision Globale :',
        'white_avg_cpl': 'CPL Moyen des Blancs :',
        'black_avg_cpl': 'CPL Moyen des Noirs :',
        'mistakes_blunders': 'Erreurs et Gaffes :',
        'blunders_text': 'Gaffes',
        'blunder_text_singular': 'Gaffe',
        'mistakes_text': 'Erreurs',
        'mistake_text_singular': 'Erreur',
        'inaccuracies_text': 'Imprécisions',
        'inaccuracy_text_singular': 'Imprécision',
        'good_move_text': 'Bon Coup',
        'eval_text': 'Éval. :',
        'best_move_text': 'Meilleur :',
        'loss_text': 'Perte :',
        'cp_text': 'c',
        'best_move_played_text': 'Meilleur Coup',
        'error_starting_stockfish': "Erreur au démarrage du moteur Stockfish : {e}. Veuillez vous assurer que '{ENGINE_PATH}' est correct et que Stockfish est installé.",
        'analysis_disabled_warning': "Les fonctionnalités d'analyse (CPL, gaffes, meilleurs coups) seront désactivées pour toutes les parties.",
        'skipping_stockfish_analysis': "Analyse Stockfish ignorée pour la partie {game_num} en raison d'une erreur moteur.",
        'exporting_game': "Exportation de la partie {current_game}/{total_games} vers LaTeX...",
        'skipping_game_error': "⚠️ Partie {game_num} ignorée en raison d'une erreur lors du traitement : {error_msg}",
        'deleting_output_dir': "Suppression du répertoire de sortie existant : {output_dir}",
        'error_deleting_dir': "Erreur lors de la suppression du répertoire {output_dir} : {error_msg}",
        'compiling_latex': "Compilation des fichiers LaTeX dans {output_dir}...",
        'main_latex_not_found': "Fichier LaTeX principal introuvable : {main_tex_file}",
        'latex_compile_failed': "Échec de la compilation LaTeX à la passe {pass_num}. Sortie :",
        'pdflatex_not_found': "Erreur : Commande pdflatex introuvable. Veuillez vous assurer que LaTeX est installé et dans votre PATH.",
        'unexpected_latex_error': "Une erreur inattendue est survenue lors de la compilation LaTeX : {error_msg}",
        'latex_compile_complete': "Compilation LaTeX terminée. Nettoyage des fichiers auxiliaires...",
        'front_matter_page_file_not_found': "Avertissement : Fichier introuvable à {path}",
        'error_reading_front_matter_page': "Avertissement : Impossible de lire le fichier {path} : {e}",
        'date_format': "%d %B %Y",
        'months': ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
                   'novembre', 'décembre'],
        'fn_white_player': 'Le carré blanc indique le joueur avec les pièces blanches.',
        'fn_black_player': 'Le carré noir indique le joueur avec les pièces noires.',
        'fn_winner': 'Une étoile apparaît à côté du nom du vainqueur de la partie.',
        'fn_date': 'La date à laquelle la partie a été jouée.',
        'fn_event': 'Le nom de l\'événement ou du tournoi.',
        'fn_time_control': 'Le contrôle de temps de la partie (par ex., 60+1 signifie 60 secondes de base avec un incrément de 1 seconde par coup).',
        'fn_notation_algebraic': 'Les coups de la partie sont listés en notation algébrique standard.',
        'fn_notation_figurine': 'Les coups de la partie sont listés en notation figurine, où un symbole représente chaque pièce.',
        'fn_analysis_summary': 'Un résumé de l\'analyse par ordinateur, incluant la perte moyenne de centipions (CPL) pour chaque joueur. Un CPL plus bas est meilleur.',
        'fn_board_diagram_all': 'Les diagrammes d\'échiquier sont affichés pour chaque paire de coups. L\'échiquier de gauche montre la position après le coup des Blancs, et celui de droite après la réponse des Noirs. Les cases de départ et d\'arrivée de chaque coup sont mises en évidence. Un roi encerclé est en échec ; un roi encerclé avec une croix est en échec et mat.',
        'fn_board_diagram_smart': 'Les diagrammes d\'échiquier ne sont affichés que pour les paires de coups "intelligentes", où au moins un coup était intéressant. L\'échiquier de gauche montre la position après le coup des Blancs, et celui de droite est après la réponse des Noirs. Les cases de départ et d\'arrivée de chaque coup sont mises en évidence. Un roi encerclé est en échec ; un roi encerclé avec une croix est en échec et mat.',
        'fn_move_reminder': 'Ce titre rappelle la paire de coups en notation algébrique standard.',
        'fn_analysis_explanation': 'L\'évaluation est toujours du point de vue des Blancs : une valeur positive indique un avantage pour les Blancs, une valeur négative un avantage pour les Noirs. Le score est soit une valeur numérique exprimée en centipions (1/100ème de pion), soit une chaîne comme MX (Mat en X coups). Par exemple, un score de +1.50c signifie que les Blancs ont un avantage de 1.5 centipion, tandis que -M3 signifie que les Noirs ont un mat forcé en 3 coups. | Perte : La perte en centipions pour le coup joué par rapport au meilleur coup du moteur. (Bon Coup, Erreur, Gaffe) : Une classification du coup basée sur la perte en centipions. Meilleur : Le coup préféré du moteur s\'il diffère de celui joué.',
        'how_to_read_title': 'Comment Lire ce Livre',
        'table_metric': 'Métrique',
        'table_white': 'Blancs',
        'table_black': 'Noirs',
        'table_avg_cpl': 'CPL Moyen',
        'table_blunders': 'Gaffes',
        'table_mistakes': 'Erreurs',
        'table_inaccuracies': 'Imprécisions',
        'term_agreement': 'Partie nulle par accord mutuel',
        'term_repetition': 'Partie nulle par répétition',
        'term_stalemate': 'Partie nulle par pat',
        'term_timeout_vs_insufficient': 'Partie nulle, temps écoulé contre matériel insuffisant',
        'term_abandoned': '{player} a gagné - partie abandonnée',
        'term_checkmate': '{player} a gagné par échec et mat',
        'term_resignation': '{player} a gagné par abandon',
        'term_time': '{player} a gagné au temps',
        'toc_title': 'Table des Matières',
    }
}

OPERA_GAME_PGN = """
[Event "A night at the opera"]
[Site "Paris FRA"]
[Date "1858.11.02"]
[EventDate "?"]
[Round "?"]
[Result "1-0"]
[White "Paul Morphy"]
[Black "Duke Karl / Count Isouard"]
[ECO "C41"]
[WhiteElo "?"]
[BlackElo "?"]
[PlyCount "33"]

1.e4 e5 2.Nf3 d6 3.d4 Bg4 4.dxe5 Bxf3 5.Qxf3 dxe5 6.Bc4 Nf6 7.Qb3 Qe7
8.Nc3 c6 9.Bg5 b5 10.Nxb5 cxb5 11.Bxb5+ Nbd7 12.O-O-O Rd8
13.Rxd7 Rxd7 14.Rd1 Qe6 15.Bxd7+ Nxd7 16.Qb8+ Nxb8 17.Rd8# 1-0
"""


def escape_latex_special_chars(text):
    """
    Escapes common LaTeX special characters in a string.
    """
    text = text.replace('\\', '\\textbackslash{}')  # Must be first!
    text = text.replace('&', '\\&')
    text = text.replace('%', '\\%')
    text = text.replace('$', '\\$')
    text = text.replace('#', '\\#')
    text = text.replace('_', '\\_')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')
    text = text.replace('~', '\\textasciitilde{}')
    text = text.replace('^', '\\textasciicircum{}')
    return text


def get_eval_string(score, lang='en'):
    """Formats a Stockfish score object into a human-readable string, now with correct mate signs."""
    if score is None:
        return "N/A"

    white_pov_score = score.white()

    if white_pov_score.is_mate():
        mate_value = white_pov_score.mate()
        if mate_value == 0:
            return "0"
        # Prepend a '+' sign if the mate value is positive
        sign = "+" if mate_value > 0 else "-"
        return f"{sign}M{abs(mate_value)}"

    # The centipawn formatting already correctly handles the sign
    return f"{white_pov_score.cp / 100.0:+.2f}{MESSAGES[lang]['cp_text']}"


def classify_move_loss(cpl, lang='en'):
    """Classifies a move based on Centipawn Loss (CPL)."""
    if cpl >= 200:
        return f"\\textbf{{{MESSAGES[lang]['blunder_text_singular']}}}"
    elif cpl >= 100:
        return f"\\textbf{{{MESSAGES[lang]['mistake_text_singular']}}}"
    elif cpl >= 50:
        return MESSAGES[lang]['inaccuracy_text_singular']
    return MESSAGES[lang]['good_move_text']


def analyze_game_with_stockfish(game, engine):
    """
    Analyzes each half-move of a game using Stockfish to get evaluations and CPL.
    Returns a list of dictionaries, where each dict contains analysis data for a half-move.
    """
    analysis_results = []  # Stores data for each half-move
    board = game.board()
    moves = list(game.mainline_moves())
    for i, move in enumerate(moves):
        analysis_before_move = engine.analyse(board, chess.engine.Limit(depth=15))
        best_move_from_pos = analysis_before_move["pv"][0] if analysis_before_move["pv"] else None
        ideal_eval_before_move = analysis_before_move["score"]
        temp_board_after_played_move = board.copy()
        temp_board_after_played_move.push(move)
        analysis_after_played_move = engine.analyse(temp_board_after_played_move, chess.engine.Limit(depth=15))
        eval_after_played_move = analysis_after_played_move["score"]
        cpl = 0
        if not ideal_eval_before_move.is_mate() and not eval_after_played_move.is_mate():
            ideal_cp_white_pov = ideal_eval_before_move.white().cp
            played_cp_white_pov = eval_after_played_move.white().cp
            if board.turn == chess.WHITE:
                cpl = max(0, ideal_cp_white_pov - played_cp_white_pov)
            else:
                cpl = max(0, played_cp_white_pov - ideal_cp_white_pov)
        analysis_results.append({
            'move_index': i,
            'played_move': move,
            'is_white_move': board.turn == chess.WHITE,
            'engine_eval_before_played_move': ideal_eval_before_move,
            'engine_best_move_from_pos': best_move_from_pos,
            'eval_after_played_move': eval_after_played_move,
            'cpl_for_move': cpl,
        })
        board.push(move)
    return analysis_results


def _get_chess_figurine(piece_symbol, default_value="", inline=True):
    if inline:
        figurine_cmd = INLINE_CHESS_SYMBOL.get(piece_symbol, default_value)
        figurine_cmd = "\\scalerel*{" + figurine_cmd + "}{Xg}"
    else:
        figurine_cmd = UNICODE_CHESS_SYMBOL.get(piece_symbol, default_value)
    return figurine_cmd


def format_pgn_date(pgn_date, lang='en'):
    """Formats a PGN date string (YYYY.MM.DD) into a localized format."""
    try:
        date_obj = datetime.strptime(pgn_date, "%Y.%m.%d").date()
        if 'months' in MESSAGES[lang]:
            month_name = MESSAGES[lang]['months'][date_obj.month - 1]
            if lang == 'fr':
                return f"{date_obj.day} {month_name} {date_obj.year}"
            else:
                return f"{month_name} {date_obj.day}, {date_obj.year}"
        else:
            return date_obj.strftime(MESSAGES[lang]["date_format"])
    except (ValueError, KeyError):
        return pgn_date


def _generate_game_notation_latex(game, notation_type, lang='en', annotated=False):
    """
    Generates the LaTeX for the game notation. For long games, it uses a two-column
    tabbing environment for perfect alignment and minimal spacing.
    """
    footnote = ""
    if annotated:
        key = 'fn_notation_figurine' if notation_type == 'figurine' else 'fn_notation_algebraic'
        footnote = f"\\footnote{{{MESSAGES[lang][key]}}}"

    latex_lines = [f"\\subsection*{{{''}}}{footnote}"]

    moves = list(game.mainline_moves())
    # Handle games with no moves to prevent LaTeX errors.
    if not moves:
        return latex_lines

    num_full_moves = (len(moves) + 1) // 2

    # The annotated example is always single-column.
    use_two_columns = num_full_moves > TWO_COLUMN_THRESHOLD and not annotated

    if use_two_columns:
        # --- TWO-COLUMN LAYOUT using tabbing for minimal, aligned columns ---
        latex_lines.append(r"\begin{multicols}{2}[\noindent]")
        latex_lines.append(r"\begin{tabbing}")
        # It sets tab stops based on the width of realistic wide moves, creating tight columns.
        latex_lines.append(r"888.\ \= O-O-O\ \= O-O-O \kill")

        temp_board = game.board()
        for i in range(0, len(moves), 2):
            move_number_str = f"{(i // 2) + 1}."

            white_move = moves[i]
            white_san = temp_board.san(white_move)

            black_san = ""
            if (i + 1) < len(moves):
                temp_board.push(white_move)
                black_move = moves[i + 1]
                black_san = temp_board.san(black_move)
                temp_board.pop()

            def get_formatted_san(san, move):
                if not san: return ""
                if notation_type == "figurine":
                    piece = temp_board.piece_at(move.from_square)
                    if piece and piece.piece_type != chess.PAWN:
                        figurine_cmd = _get_chess_figurine(piece.symbol())
                        # For figurines, we only take the part of the SAN after the piece letter
                        san_suffix = san[1:] if san and san[0].upper() in 'NBRQK' else san
                        return figurine_cmd + escape_latex_special_chars(san_suffix)
                return escape_latex_special_chars(san)

            white_str = get_formatted_san(white_san, white_move)
            black_str = get_formatted_san(black_san, moves[i + 1]) if black_san else ""

            # The first item on the line is NOT preceded by \>
            latex_lines.append(f"{move_number_str} \\> {white_str} \\> {black_str} \\\\")

            temp_board.push(white_move)
            if (i + 1) < len(moves):
                temp_board.push(moves[i + 1])

        latex_lines.append(r"\end{tabbing}")
        latex_lines.append(r"\end{multicols}")

    else:
        # --- SINGLE-COLUMN LAYOUT FOR SHORTER GAMES (Unchanged) ---
        latex_lines.append("\\noindent")
        latex_lines.append("\\begin{tabularx}{\\linewidth}{l l l}")
        board = game.board()

        if annotated and len(moves) > 16:
            moves = moves[:16]

        for i in range(0, len(moves), 2):
            move_number = (i // 2) + 1
            white_move = moves[i]
            white_san = board.san(white_move)
            white_move_str_latex = ""
            if notation_type == "figurine":
                moving_piece = board.piece_at(white_move.from_square)
                if moving_piece and moving_piece.piece_type != chess.PAWN:
                    piece_symbol = moving_piece.symbol()
                    figurine_cmd = _get_chess_figurine(piece_symbol)
                    # For figurines, we only take the part of the SAN after the piece letter
                    san_suffix = white_san[1:] if white_san and white_san[0].upper() in 'NBRQK' else white_san
                    white_move_str_latex = figurine_cmd + escape_latex_special_chars(san_suffix)
                else:
                    white_move_str_latex = escape_latex_special_chars(white_san)
            else:
                white_move_str_latex = escape_latex_special_chars(white_san)
            board.push(white_move)

            black_move_str_latex = ""
            if (i + 1) < len(moves):
                black_move = moves[i + 1]
                black_san = board.san(black_move)
                if notation_type == "figurine":
                    moving_piece = board.piece_at(black_move.from_square)
                    if moving_piece and moving_piece.piece_type != chess.PAWN:
                        piece_symbol = moving_piece.symbol()
                        figurine_cmd = _get_chess_figurine(piece_symbol)
                        # For figurines, we only take the part of the SAN after the piece letter
                        san_suffix = black_san[1:] if black_san and black_san[0].upper() in 'NBRQK' else black_san
                        black_move_str_latex = figurine_cmd + escape_latex_special_chars(san_suffix)
                    else:
                        black_move_str_latex = escape_latex_special_chars(black_san)
                else:
                    black_move_str_latex = escape_latex_special_chars(black_san)
                board.push(black_move)
            latex_lines.append(f"{move_number}. & {white_move_str_latex} & {black_move_str_latex}\\\\")
        latex_lines.append("\\end{tabularx}")

    return latex_lines


def _generate_game_metadata_latex(game, game_index, lang='en'):
    """
    Generates the LaTeX for the game's metadata section.
    The section title is made invisible but is added to the TOC and page headers.
    """
    latex_lines = []
    header = game.headers.get("Event", MESSAGES[lang]['game_event_default'])
    white = game.headers.get("White", MESSAGES[lang]['white_player_default'])
    black = game.headers.get("Black", MESSAGES[lang]['black_player_default'])
    result = game.headers.get("Result", "*")
    white_escaped = escape_latex_special_chars(white)
    black_escaped = escape_latex_special_chars(black)
    header_escaped = escape_latex_special_chars(header)
    title_string = f"{white_escaped} vs {black_escaped} ({result}) - {header_escaped}"
    latex_lines.append("\\newpage")
    latex_lines.append(f"\\addcontentsline{{toc}}{{section}}{{{title_string}}}")
    latex_lines.append(f"\\markright{{{title_string}}}")
    latex_lines.extend(_generate_game_summary_latex(game, lang))
    return latex_lines


def _generate_analysis_summary_latex(analysis_data, lang='en', annotated=False):
    """
    Generates the LaTeX for the analysis summary section, formatted as a table.
    """
    fn = lambda key: f"\\footnote{{{MESSAGES[lang][key]}}}" if annotated else ""
    if not analysis_data:
        return []
    total_moves_analyzed = len(analysis_data)
    white_moves_count = sum(1 for d in analysis_data if d['is_white_move'])
    black_moves_count = total_moves_analyzed - white_moves_count
    white_total_cpl = sum(d['cpl_for_move'] for d in analysis_data if d['is_white_move'])
    black_total_cpl = sum(d['cpl_for_move'] for d in analysis_data if not d['is_white_move'])
    white_avg_cpl = (white_total_cpl / white_moves_count) if white_moves_count > 0 else 0
    black_avg_cpl = (black_total_cpl / black_moves_count) if black_moves_count > 0 else 0
    white_blunders = sum(1 for d in analysis_data if d['is_white_move'] and d['cpl_for_move'] >= 200)
    black_blunders = sum(1 for d in analysis_data if not d['is_white_move'] and d['cpl_for_move'] >= 200)
    white_mistakes = sum(1 for d in analysis_data if d['is_white_move'] and 100 <= d['cpl_for_move'] < 200)
    black_mistakes = sum(1 for d in analysis_data if not d['is_white_move'] and 100 <= d['cpl_for_move'] < 200)
    white_inaccuracies = sum(1 for d in analysis_data if d['is_white_move'] and 50 <= d['cpl_for_move'] < 100)
    black_inaccuracies = sum(1 for d in analysis_data if not d['is_white_move'] and 50 <= d['cpl_for_move'] < 100)
    latex_lines = [f"\\subsection*{{{''}}}{fn('fn_analysis_summary')}"]
    header_metric = ""
    header_white = f"\\textbf{{{MESSAGES[lang]['table_white']}}}"
    header_black = f"\\textbf{{{MESSAGES[lang]['table_black']}}}"
    avg_cpl_label = MESSAGES[lang]['table_avg_cpl']
    latex_lines.append(r"\begin{tabularx}{\linewidth}{l c c}")
    latex_lines.append(f"{header_metric} & {header_white} & {header_black} \\\\ \\cline{{1-1}} \\cline{{2-3}}")
    latex_lines.append(f"{avg_cpl_label} & {white_avg_cpl:.2f} & {black_avg_cpl:.2f} \\\\")
    latex_lines.append(f"{MESSAGES[lang]['table_blunders']} & {white_blunders} & {black_blunders} \\\\")
    latex_lines.append(f"{MESSAGES[lang]['table_mistakes']} & {white_mistakes} & {black_mistakes} \\\\")
    latex_lines.append(f"{MESSAGES[lang]['table_inaccuracies']} & {white_inaccuracies} & {black_inaccuracies} \\\\")
    latex_lines.append(r"\end{tabularx}")
    return latex_lines


def _generate_board_analysis_latex(game, analysis_data, show_mover, board_scope, lang='en', annotated=False, args=None):
    """
    Generates the LaTeX for move-by-move board displays, with correctly placed footnotes and check/checkmate markers.
    """
    fn = lambda key: f"\\protect\\footnote{{{MESSAGES[lang][key]}}}" if annotated else ""
    latex_lines = []
    if not analysis_data:
        return latex_lines

    board_for_display = game.board()
    moves_list = list(game.mainline_moves())
    nodes = list(game.mainline())
    all_calculated_move_pairs = []

    for i in range(0, len(moves_list), 2):
        current_move_pair_text = f"{(i // 2) + 1}."
        fen1, marked_sq1, fen2, marked_sq2 = "", "", "", ""
        king_mark_opts1, king_mark_opts2 = "", ""  # variables for check marks

        white_move_obj = moves_list[i] if i < len(moves_list) else None
        white_node = nodes[i] if white_move_obj else None

        black_move_obj = moves_list[i + 1] if (i + 1) < len(moves_list) else None
        black_node = nodes[i + 1] if black_move_obj else None

        white_analysis_data = analysis_data[i] if white_move_obj and i < len(analysis_data) else None
        black_analysis_data = analysis_data[i + 1] if black_move_obj and (i + 1) < len(analysis_data) else None

        has_cpl_in_pair = (white_analysis_data and white_analysis_data['cpl_for_move'] > 0) or \
                          (black_analysis_data and black_analysis_data['cpl_for_move'] > 0)

        if white_move_obj:
            current_move_pair_text += f" {escape_latex_special_chars(board_for_display.san(white_move_obj))}"
            if board_for_display.is_castling(white_move_obj):
                king_from_sq, rook_from_sq = white_move_obj.from_square, chess.H1 if board_for_display.is_kingside_castling(
                    white_move_obj) else chess.A1
                marked_sq1 = f"markfields={{{chess.square_name(king_from_sq)},{chess.square_name(rook_from_sq)}}}"
            else:
                marked_sq1 = f"markfields={{{chess.square_name(white_move_obj.from_square)},{chess.square_name(white_move_obj.to_square)}}}"
            board_for_display.push(white_move_obj)
            fen1 = board_for_display.board_fen()

            # Check for check/checkmate against Black's king
            if board_for_display.is_checkmate():
                king_square = chess.square_name(board_for_display.king(chess.BLACK))
                king_mark_opts1 = f",markstyle=circle,markfield={{{king_square}}},markstyle=cross,markfield={{{king_square}}}"
            elif board_for_display.is_check():
                king_square = chess.square_name(board_for_display.king(chess.BLACK))
                king_mark_opts1 = f",markstyle=circle,markfield={{{king_square}}}"

        if black_move_obj:
            current_move_pair_text += f" {escape_latex_special_chars(board_for_display.san(black_move_obj))}"
            if board_for_display.is_castling(black_move_obj):
                king_from_sq, rook_from_sq = black_move_obj.from_square, chess.H8 if board_for_display.is_kingside_castling(
                    black_move_obj) else chess.A8
                marked_sq2 = f"markfields={{{chess.square_name(king_from_sq)},{chess.square_name(rook_from_sq)}}}"
            else:
                marked_sq2 = f"markfields={{{chess.square_name(black_move_obj.from_square)},{chess.square_name(black_move_obj.to_square)}}}"
            board_for_display.push(black_move_obj)
            fen2 = board_for_display.board_fen()

            # Check for check/checkmate against White's king
            if board_for_display.is_checkmate():
                king_square = chess.square_name(board_for_display.king(chess.WHITE))
                king_mark_opts2 = f",markstyle=circle,markfield={{{king_square}}},markstyle=cross,markfield={{{king_square}}}"
            elif board_for_display.is_check():
                king_square = chess.square_name(board_for_display.king(chess.WHITE))
                king_mark_opts2 = f",markstyle=circle,markfield={{{king_square}}}"
        else:
            fen2, marked_sq2 = fen1, ""

        all_calculated_move_pairs.append(
            (current_move_pair_text, fen1, marked_sq1, king_mark_opts1, white_analysis_data, fen2, marked_sq2,
             king_mark_opts2, black_analysis_data, has_cpl_in_pair, white_node, black_node))

    move_pairs_to_display = all_calculated_move_pairs if board_scope == "all" else [pair for pair in
                                                                                    all_calculated_move_pairs if
                                                                                    pair[9]]
    if annotated:
        move_pairs_to_display = all_calculated_move_pairs[5:6]

    board_size = PAPER_SIZE_SETTINGS[args.paper_size]['board_size']
    for i, (move_text, fen1, marked_sq1, king_mark_opts1, white_analysis, fen2, marked_sq2, king_mark_opts2,
            black_analysis, _, white_node,
            black_node) in enumerate(move_pairs_to_display):

        move_title_footnote = fn('fn_move_reminder') if i == 0 and annotated else ""
        latex_lines.append(f"\\subsubsection*{{{move_text}{move_title_footnote}}}")

        deferred_footnotetexts = []

        board_footnote_mark = ""
        if i == 0 and annotated:
            board_footnote_mark = "\\footnotemark "
            key = 'fn_board_diagram_smart' if board_scope == 'smart' else 'fn_board_diagram_all'
            deferred_footnotetexts.append(f"\\footnotetext{{{MESSAGES[lang][key]}}}")

        analysis_footnote_mark = ""
        if i == 0 and annotated and (white_analysis or black_analysis):
            analysis_footnote_mark = "\\footnotemark "
            deferred_footnotetexts.append(f"\\footnotetext{{{MESSAGES[lang]['fn_analysis_explanation']}}}")

        def format_analysis(analysis, node):
            if not analysis:
                return "", ""

            comment_footnote_mark = ""
            comment = node.comment if node and node.comment and not node.comment.strip().startswith('[%') else None
            if comment:
                comment_footnote_mark = "\\footnotemark "
                deferred_footnotetexts.append(f"\\footnotetext{{{escape_latex_special_chars(comment)}}}")

            eval_str = f"\\textit{{{MESSAGES[lang]['eval_text']} {get_eval_string(analysis['eval_after_played_move'], lang)}}}"

            if analysis['played_move'] != analysis['engine_best_move_from_pos'] and not analysis[
                'engine_eval_before_played_move'].is_mate():
                loss_str = f"\\textit{{{MESSAGES[lang]['loss_text']} {analysis['cpl_for_move']}}}{MESSAGES[lang]['cp_text']}"
                classification = classify_move_loss(analysis['cpl_for_move'], lang)
                best_move_str = f"\\textit{{{MESSAGES[lang]['best_move_text']} {escape_latex_special_chars(analysis['engine_best_move_from_pos'].uci())}}}"
                separator = "\\text{\\textbar}"
                line1 = f"{comment_footnote_mark}{eval_str} {separator} {loss_str}"
                line2 = f"{classification} ({best_move_str})"
                return line1, line2
            else:
                line1 = f"{comment_footnote_mark}{eval_str} (\\textit{{{MESSAGES[lang]['best_move_played_text']}}})"
                return line1, "\\strut"

        white_line1, white_line2 = format_analysis(white_analysis, white_node)
        black_line1, black_line2 = format_analysis(black_analysis, black_node)

        board1_cmd = f"\\chessboard[setfen={{ {fen1} }}, boardfontsize={board_size}, mover=b, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, {marked_sq1}{king_mark_opts1}]"

        board2_cmd = ""
        if marked_sq2:
            board2_cmd = f"\\chessboard[setfen={{ {fen2} }}, boardfontsize={board_size}, mover=w, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, {marked_sq2}{king_mark_opts2}]"

        latex_lines.append(r"\begin{minipage}{\linewidth}")
        latex_lines.append(board_footnote_mark)
        latex_lines.append("\\begin{tabularx}{\\linewidth}{X X}")
        latex_lines.append(f"{board1_cmd} & {board2_cmd} \\\\")
        latex_lines.append("\\end{tabularx}")

        if white_analysis or black_analysis:
            latex_lines.append("\\begin{tabularx}{\\linewidth}{X X}")
            latex_lines.append(f"{analysis_footnote_mark}{white_line1} & {black_line1} \\\\")
            latex_lines.append(f"{white_line2} & {black_line2} \\\\")
            latex_lines.append("\\end{tabularx}")

        latex_lines.append(r"\end{minipage}")

        if deferred_footnotetexts:
            latex_lines.append(f"\\addtocounter{{footnote}}{{-{len(deferred_footnotetexts)}}}")
            for text in deferred_footnotetexts:
                latex_lines.append(f"\\stepcounter{{footnote}}{text}")

    return latex_lines


def _generate_game_summary_latex(game, lang='en', annotated=False):
    """
    Generates the LaTeX for the game's summary box (players, date, event).
    """
    fn = lambda key: f"\\footnote{{{MESSAGES[lang][key]}}}" if annotated else ""
    latex_lines = []
    white = game.headers.get("White", MESSAGES[lang]['white_player_default'])
    black = game.headers.get("Black", MESSAGES[lang]['black_player_default'])
    date = game.headers.get("Date", "Unknown Date")
    event = game.headers.get("Event", "Casual Game")
    result = game.headers.get("Result", "*")
    time_control = game.headers.get("TimeControl", "?")
    standard_tc = translate_time_control(time_control)
    formatted_date = format_pgn_date(date, lang)
    white_escaped = escape_latex_special_chars(white)
    black_escaped = escape_latex_special_chars(black)
    date_escaped = escape_latex_special_chars(formatted_date)
    event_escaped = escape_latex_special_chars(event)
    tc_escaped = escape_latex_special_chars(f"({standard_tc})")
    winner_symbol = r" $\star$"
    if annotated:
        winner_symbol += fn('fn_winner')
    if result == "1-0":
        white_escaped += winner_symbol
    elif result == "0-1":
        black_escaped += winner_symbol
    latex_lines.append(r"\vspace{0.5\baselineskip}")
    white_line = fr"\noindent $\Box$ \textbf{{{white_escaped}}}{fn('fn_white_player')} \hfill \textit{{{date_escaped}}}{fn('fn_date')} \\"
    black_line = fr"\noindent $\blacksquare$ \textbf{{{black_escaped}}}{fn('fn_black_player')} \hfill \textit{{{event_escaped}}}{fn('fn_event')} {tc_escaped}{fn('fn_time_control')}"
    latex_lines.append(white_line)
    latex_lines.append(black_line)
    latex_lines.append(r"\vspace{0.5\baselineskip}\hrule\vspace{\baselineskip}")
    return latex_lines


def translate_time_control(non_standard_tc: str) -> str:
    """
    Translates a non-standard TimeControl string from sources like chess.com
    into a more PGN-standard compliant format.
    """
    if not non_standard_tc:
        return "?"
    if '+' in non_standard_tc:
        try:
            base, increment = map(int, non_standard_tc.split('+'))
            return f"{base}+{increment}"
        except ValueError:
            return "?"
    if '/' in non_standard_tc:
        try:
            parts = non_standard_tc.split('/')
            seconds = int(parts[1])
            return str(seconds)
        except (ValueError, IndexError):
            return "?"
    try:
        base_time = int(non_standard_tc)
        return str(base_time)
    except ValueError:
        return "?"


def _generate_termination_latex(game, lang='en'):
    """
    Parses the game's Termination header and returns a translated LaTeX string.
    """
    termination = game.headers.get("Termination")
    if not termination:
        return []

    # Map the raw PGN termination reasons to our message keys
    termination_map = {
        "Game drawn by agreement": "term_agreement",
        "Game drawn by repetition": "term_repetition",
        "Game drawn by stalemate": "term_stalemate",
        "Game drawn by timeout vs insufficient material": "term_timeout_vs_insufficient",
        "won - game abandoned": "term_abandoned",
        "won by checkmate": "term_checkmate",
        "won by resignation": "term_resignation",
        "won on time": "term_time",
    }

    player_name = ""
    reason_key = ""
    prefix = "\\nobreak\\strut"

    # Split the termination string to find the player and the reason
    for reason, key in termination_map.items():
        if reason in termination:
            # The player's name is the part of the string BEFORE the reason
            player_name = termination.replace(reason, "").strip()
            reason_key = key
            break

    if not reason_key:
        # Fallback for unknown termination reasons
        return [f"{prefix}\\par\\textbf{{{escape_latex_special_chars(termination)}}}"]

    # Get the translated message
    message_template = MESSAGES[lang].get(reason_key, "")

    # Substitute the player's name into the translated string
    # and escape any special LaTeX characters in the name.
    final_message = message_template.format(player=escape_latex_special_chars(player_name))

    # Return the final message, bolded and on a new paragraph.
    return [f"{prefix}\\par\\textbf{{{final_message}}}"]


def export_game_to_latex(game, game_index, output_dir, analysis_data, args, annotated=False):
    """
    Exports a single chess game to a LaTeX file, now with annotation support.
    """
    latex = []
    lang = args.language
    if annotated:
        # For the annotated example, we don't need the standard metadata header
        latex.extend(_generate_game_summary_latex(game, lang, annotated=True))
    else:
        latex.extend(_generate_game_metadata_latex(game, game_index, lang))

    latex.extend(_generate_game_notation_latex(game, args.notation_type, lang, annotated=annotated))

    if analysis_data:
        latex.extend(_generate_analysis_summary_latex(analysis_data, lang, annotated=annotated))

    if args.display_boards:
        latex.extend(
            _generate_board_analysis_latex(game, analysis_data, False, args.board_scope, lang, annotated=annotated,
                                           args=args))

    # Add the termination reason at the very end of the game content.
    latex.extend(_generate_termination_latex(game, lang))

    file_name = "how_to_read_example.tex" if annotated else f"game_{game_index:03}.tex"
    with open(output_dir / file_name, "w", encoding='utf-8') as f:
        f.write("\n".join(latex))


def generate_how_to_read_section(tex_master, args, output_dir, engine):
    """Generates the 'How to Read This Book' section using footnotes."""
    import io
    lang = args.language
    print("Generating 'How to Read This Book' section...")
    title = MESSAGES[lang]['how_to_read_title']

    tex_master.append(r"\cleardoublepage")
    tex_master.append(f"\\addcontentsline{{toc}}{{section}}{{{title}}}")
    # Use \markright for a section-level header
    tex_master.append(f"\\markright{{{title}}}")

    pgn_io = io.StringIO(OPERA_GAME_PGN)
    game = chess.pgn.read_game(pgn_io)
    analysis_data = []
    if engine:
        analysis_data = analyze_game_with_stockfish(game, engine)

    export_game_to_latex(
        game, 0, output_dir, analysis_data, args, annotated=True
    )

    tex_master.append(r"\input{how_to_read_example.tex}")
    tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")
    tex_master.append(r"\cleardoublepage")


def delete_output_directory(output_dir_path, lang='en'):
    """Deletes the output directory if it exists."""
    output_dir = Path(output_dir_path)
    if output_dir.exists() and output_dir.is_dir():
        print(MESSAGES[lang]['deleting_output_dir'].format(output_dir=output_dir))
        try:
            shutil.rmtree(output_dir)
        except OSError as e:
            print(MESSAGES[lang]['error_deleting_dir'].format(output_dir=output_dir, error_msg=e), file=sys.stderr)
            sys.exit(1)


def compile_latex_to_pdf(output_dir_path, main_tex_file="chess_book.tex", lang='en'):
    """Compiles the LaTeX files to PDF and cleans up auxiliary files."""
    output_dir = Path(output_dir_path)
    main_tex_path = output_dir / main_tex_file
    if not main_tex_path.exists():
        print(MESSAGES[lang]['main_latex_not_found'].format(main_tex_file=main_tex_path), file=sys.stderr)
        return
    print(MESSAGES[lang]['compiling_latex'].format(output_dir=output_dir))
    for i in range(LATEX_COMPILE_PASSES):
        try:
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", main_tex_file],
                cwd=output_dir,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                print(MESSAGES[lang]['latex_compile_failed'].format(pass_num=i + 1), file=sys.stderr)
                print(result.stdout, file=sys.stderr)
                print(result.stderr, file=sys.stderr)
        except FileNotFoundError:
            print(MESSAGES[lang]['pdflatex_not_found'], file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(MESSAGES[lang]['unexpected_latex_error'].format(error_msg=e), file=sys.stderr)
            sys.exit(1)
    print(MESSAGES[lang]['latex_compile_complete'])
    aux_extensions = ['.aux', '.log', '.lof', '.toc', '.out', '.fls', '.fdb_latexmk', '.synctex.gz']
    for f in output_dir.iterdir():
        if f.suffix in aux_extensions or (f.is_file() and (
                f.name.startswith("game_") or f.name == "how_to_read_example.tex") and f.suffix == '.tex'):
            try:
                f.unlink()
            except OSError as e:
                print(f"Error deleting auxiliary file {f}: {e}", file=sys.stderr)


def _add_front_matter_page_to_latex(tex_master_list, file_path, lang='en'):
    """
    Adds the front matter content to the LaTeX master list if a file is provided.
    """
    if file_path:
        content_path = Path(file_path)
        if content_path.exists():
            try:
                with open(content_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                content_processed = escape_latex_special_chars(content)
                while '\n\n\n' in content_processed:
                    content_processed = content_processed.replace('\n\n\n', '\n\n')
                content_processed = content_processed.replace('\n\n', r"\par\vspace{\baselineskip}\noindent ")
                content_processed = content_processed.replace('\n', r"\\* ")
                formatted_content = (
                        r"\newpage" + "\n" +
                        r"\thispagestyle{empty}" + "\n" +
                        r"\vspace*{.3\textheight}" + "\n" +
                        r"\begin{flushright}" + "\n" +
                        r"\parbox{0.7\linewidth}{\raggedleft" + "\n" +
                        content_processed + "\n" +
                        r"}" + "\n" +
                        r"\end{flushright}" + "\n"
                )
                tex_master_list.append(formatted_content)
            except Exception as e:
                print(MESSAGES[lang]['error_reading_front_matter_page'].format(path=content_path, e=e), file=sys.stderr)
        else:
            print(MESSAGES[lang]['front_matter_page_file_not_found'].format(path=content_path), file=sys.stderr)


def _find_book_part_file(directory, basename):
    """Finds a file with a given basename, checking for .tex and .txt extensions."""
    if not directory:
        return None, None
    base_path = Path(directory) / basename
    if (tex_file := base_path.with_suffix('.tex')).exists():
        return tex_file, 'latex'
    if (txt_file := base_path.with_suffix('.txt')).exists():
        return txt_file, 'text'
    return None, None


def _format_dedication_epigraph_txt(content):
    """Formats raw text for a dedication or epigraph page (right-aligned)."""
    content_processed = escape_latex_special_chars(content)
    content_processed = content_processed.replace('\n\n', r"\par\vspace{\baselineskip}\par")
    content_processed = content_processed.replace('\n', r"\\* ")
    return (
            r"\newpage" + "\n" +
            r"\thispagestyle{empty}" + "\n" +
            r"\vspace*{.3\textheight}" + "\n" +
            r"\begin{flushright}" + "\n" +
            r"\parbox{0.7\linewidth}{\raggedleft" + "\n" +
            content_processed + "\n" +
            r"}" + "\n" +
            r"\end{flushright}" + "\n"
    )


def _format_preface_txt(content):
    """Formats raw text for a preface page (justified with a title)."""
    title = "Preface"  # You can expand this to be dynamic if needed

    # Process text to respect paragraph breaks
    paragraphs = content.strip().split('\n\n')
    content_processed = r"\par ".join([escape_latex_special_chars(p) for p in paragraphs])

    return (
            r"\cleardoublepage" + "\n" +
            f"\\section*{{{title}}}" + "\n" +
            f"\\addcontentsline{{toc}}{{section}}{{{title}}}" + "\n" +
            # This command clears the right-hand header for this section.
            f"\\markright{{{''}}}" + "\n" +
            r"\thispagestyle{fancy}" + "\n" +
            # Add vertical space after the title. Adjust '2\baselineskip' for more/less space.
            r"\vspace*{2\baselineskip}" + "\n" +
            content_processed + "\n"
    )


def _process_book_part(directory, basename):
    """
    Finds a book part file and returns its processed LaTeX content.
    """
    file_path, file_type = _find_book_part_file(directory, basename)
    if not file_path:
        return ""

    content = file_path.read_text(encoding='utf-8')

    if file_type == 'latex':
        return content  # Use LaTeX file as is

    if file_type == 'text':
        if basename in ["dedication", "epigraph"]:
            return _format_dedication_epigraph_txt(content)
        if basename == "preface":
            return _format_preface_txt(content)
        # Placeholder for back-cover text formatting if needed in the future
        # if basename == "back-cover":
        #     return _format_back_cover_txt(content)

    return ""  # Ignore unknown files

def generate_chess_book(args):
    """
    Orchestrates the creation of the chess book from command-line arguments.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(args.pgn_file) as f:
        games = list(iter(lambda: chess.pgn.read_game(f), None))

    settings = PAPER_SIZE_SETTINGS[args.paper_size]

    # --- Process Book Design Directory ---
    design_dir = args.book_design_dir
    front_cover_content = _process_book_part(design_dir, "front-cover")
    dedication_content = _process_book_part(design_dir, "dedication")
    epigraph_content = _process_book_part(design_dir, "epigraph")
    preface_content = _process_book_part(design_dir, "preface")
    back_cover_content = _process_book_part(design_dir, "back-cover")

    # Check if any front matter content was actually loaded.
    has_front_matter = any([front_cover_content, dedication_content, epigraph_content, preface_content])

    # --- Assemble the Book in Order ---
    tex_master = []
    tex_master.append(f"\\renewcommand{{\\contentsname}}{{{MESSAGES[args.language]['toc_title']}}}")
    tex_master.append(get_latex_header_part1(settings))

    # 1. Front Cover
    if front_cover_content:
        tex_master.append(front_cover_content)

    # Add a blank page
    if has_front_matter:
        tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")

    # 2. Dedication & Epigraph
    if dedication_content:
        tex_master.append(dedication_content)
    if epigraph_content:
        tex_master.append(epigraph_content)

    # 3. Table of Contents
    tex_master.append(LATEX_HEADER_PART2_TOC)

    # 4. Preface
    if preface_content:
        tex_master.append(preface_content)

    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        engine.configure({"Threads": 2, "Hash": 128})
    except Exception as e:
        print(MESSAGES[args.language]['error_starting_stockfish'].format(e=e, ENGINE_PATH=ENGINE_PATH))
        print(MESSAGES[args.language]['analysis_disabled_warning'])
    if args.how_to_read:
        generate_how_to_read_section(tex_master, args, output_dir, engine)
    for idx, game in enumerate(games):
        try:
            print(MESSAGES[args.language]['exporting_game'].format(current_game=idx + 1, total_games=len(games)))
            analysis_data = []
            if engine:
                analysis_data = analyze_game_with_stockfish(game, engine)
            else:
                print(MESSAGES[args.language]['skipping_stockfish_analysis'].format(game_num=idx + 1))

            export_game_to_latex(
                game, idx + 1, output_dir, analysis_data, args
            )
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(MESSAGES[args.language]['skipping_game_error'].format(game_num=idx + 1, error_msg=e))

    # Add a blank page at the very end if there is front matter.
    if has_front_matter:
        tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")

    # 5. Back Cover at the very end
    if back_cover_content:
        tex_master.append(back_cover_content)

    tex_master.append(LATEX_FOOTER)
    with open(output_dir / "chess_book.tex", "w", encoding='utf-8') as f:
        f.write("\n".join(tex_master))
    if engine:
        engine.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a chess book from PGN files.")
    parser.add_argument("pgn_file", type=str, help="Path to the PGN file.")
    parser.add_argument("output_dir", type=str, help="Directory where the LaTeX files and the final PDF will be generated.")
    parser.add_argument("--book_design_dir", type=str,
                        help="Directory containing LaTeX/text files for book parts (front-cover, dedication, etc.).")
    parser.add_argument("--notation_type", type=str, choices=["algebraic", "figurine"], default="figurine",
                        help="Type of notation to use: 'algebraic' or 'figurine' (default: 'figurine').")
    parser.add_argument("--display_boards", action="store_true", help="Enable display of chessboards. If off (default), only notation is displayed.")
    parser.add_argument("--board_scope", type=str, choices=["all", "smart"], default="smart",
                        help="Specify whether to display boards for 'all' moves or only 'smart' moves (i.e., moves with CPL > 0, default: 'smart').")
    parser.add_argument("--language", type=str, choices=["en", "fr"], default="en", help="Language for text.")
    parser.add_argument("--paper_size", type=str, choices=['a3', 'a4', 'a5'], default='a4', help="Paper size for the output PDF (default: 'a4').")
    parser.add_argument("--how_to_read", action="store_true", help="Add 'How to Read This Book' section.")
    args = parser.parse_args()
    delete_output_directory(args.output_dir, args.language)
    generate_chess_book(args)
    compile_latex_to_pdf(args.output_dir, lang=args.language)