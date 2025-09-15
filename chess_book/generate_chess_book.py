import json
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent
import argparse
import shutil  # For deleting directories
import subprocess  # For running pdflatex
import io
import re

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

        % --- Redefine \cleardoublepage to use an empty page style for blank pages ---
        \makeatletter
        \def\cleardoublepage{{\clearpage\if@twoside \ifodd\c@page\else
        \hbox{{}}\thispagestyle{{empty}}\newpage\if@twocolumn\hbox{{}}\newpage\fi\fi\fi}}
        \makeatother

        \pagestyle{{fancy}}
        \fancyhf{{}}
        \renewcommand{{\headrulewidth}}{{0pt}}

        % RO = Right header on Odd pages (current section/game title)
        % CE = Center header on Even pages (book title)
        \fancyhead[RO]{{\nouppercase{{\rightmark}}}}
        \fancyhead[CE]{{\nouppercase{{\booktitle}}}}

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
[ECOUrl "https://www.chess.com/openings/Philidor-Defense-Accepted-Traditional-Variation"]
[WhiteElo "?"]
[BlackElo "?"]
[PlyCount "33"]

1.e4 e5 2.Nf3 d6 3.d4 Bg4 4.dxe5 Bxf3 5.Qxf3 dxe5 6.Bc4 Nf6 7.Qb3 Qe7
8.Nc3 c6 9.Bg5 b5 10.Nxb5 cxb5 11.Bxb5+ Nbd7 12.O-O-O Rd8
13.Rxd7 Rxd7 14.Rd1 Qe6 15.Bxd7+ Nxd7 16.Qb8+ Nxb8 17.Rd8# 1-0
"""

# Global variable to hold the loaded messages
MESSAGES = {}
OPENINGS = {}


def load_messages(lang='en'):
    """Loads the localized messages from the corresponding JSON file."""
    global MESSAGES
    try:
        # Assuming the script is run from the root directory where 'locales' is located
        file_path = Path(f"locales/{lang}.json")
        with open(file_path, 'r', encoding='utf-8') as f:
            MESSAGES = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(
            f"Error: Could not load the language file for '{lang}'. Please check the 'locales' directory. Details: {e}",
            file=sys.stderr)
        sys.exit(1)


def load_openings():
    """Loads the chess openings data from the JSON file."""
    global OPENINGS
    try:
        file_path = Path("data/eco_openings.json")
        with open(file_path, 'r', encoding='utf-8') as f:
            OPENINGS = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Could not load the openings file. Please check for 'eco_openings.json'. Details: {e}",
              file=sys.stderr)
        sys.exit(1)


def translate_san_move(san_move):
    """
    Translates English piece letters in SAN to a localized version,
    correctly handling all promotions, checks, and checkmates.
    """
    if not san_move:
        return ""

    # 1. Check for promotion (e.g., "e8=Q", "fxg1=N#")
    if "=" in san_move:
        base_move, promotion_part = san_move.split('=', 1)
        # The piece is the first character of the part after '='
        promotion_piece = promotion_part[0]

        if promotion_piece in MESSAGES['piece_letters']:
            localized_piece = MESSAGES['piece_letters'][promotion_piece]
            # Re-add any trailing characters like '+' or '#'
            trailing_chars = promotion_part[1:]
            return f"{base_move}={localized_piece}{trailing_chars}"
        else:
            return san_move  # Fallback for safety

    # 2. Handle regular piece moves (e.g., "Nf3", "Rxe5+")
    if san_move[0] in MESSAGES['piece_letters']:
        english_piece = san_move[0]
        localized_piece = MESSAGES['piece_letters'][english_piece]
        return localized_piece + san_move[1:]

    # 3. Handle pawn moves and castling
    return san_move


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
    return f"{white_pov_score.cp / 100.0:+.2f}{MESSAGES['cp_text']}"


def classify_move_loss(cpl, lang='en'):
    """Classifies a move based on Centipawn Loss (CPL)."""
    if cpl >= 200:
        return f"\\textbf{{{MESSAGES['blunder_text_singular']}}}"
    elif cpl >= 100:
        return f"\\textbf{{{MESSAGES['mistake_text_singular']}}}"
    elif cpl >= 50:
        return MESSAGES['inaccuracy_text_singular']
    return MESSAGES['good_move_text']


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
        if 'months' in MESSAGES:
            month_name = MESSAGES['months'][date_obj.month - 1]
            if lang == 'fr':
                return f"{date_obj.day} {month_name} {date_obj.year}"
            else:
                return f"{month_name} {date_obj.day}, {date_obj.year}"
        else:
            return date_obj.strftime(MESSAGES["date_format"])
    except (ValueError, KeyError):
        return pgn_date


def _find_opening_data(game):
    """
    Finds opening data from the loaded OPENINGS dictionary based on game headers.
    """
    eco_url = game.headers.get("ECOUrl", "")
    eco_code = game.headers.get("ECO", "")

    if not eco_url or not eco_code:
        return None

    try:
        opening_key_raw = eco_url.split('/')[-1]
        parts = opening_key_raw.split('-')
        opening_key_parts = []
        for part in parts:
            if part and not (part[0].isdigit() and '.' in part) and part not in ['O', 'O-O', 'O-O-O']:
                opening_key_parts.append(part)
            else:
                break
        opening_key = '-'.join(opening_key_parts)
    except IndexError:
        return None

    # Primary lookup method
    opening_data = OPENINGS.get(opening_key)
    if opening_data and opening_data.get("ECO") == eco_code:
        return opening_data

    # Fallback search if the primary method fails
    for key, data in OPENINGS.items():
        if data.get("ECO") == eco_code:
            # A simple heuristic: check if the key from the JSON is a substring of the URL key
            if key in opening_key:
                return data
    return None


def _generate_opening_info_latex(game, notation_type, lang='en', annotated=False, args=None):
    """
    Generates the LaTeX for the chess opening section with custom layout,
    self-contained within this function.
    """
    latex_lines = []
    opening_data = _find_opening_data(game)

    if not opening_data:
        return []

    eco_code = opening_data.get("ECO", "")
    opening_name = opening_data.get('lang', {}).get(lang, opening_data.get('lang', {}).get('en', ''))
    opening_moves = opening_data.get('moves', '')

    if not opening_name or not opening_moves:
        return []

    fn = lambda key: f"\\footnote{{{MESSAGES[key]}}}" if annotated else ""

    # The subsection is now invisible, serving only as an anchor for the footnote.
    latex_lines.append(f"\\subsection*{{{''}}}{fn('fn_opening_section')}")

    marked_sq_option = ""
    try:
        pgn = io.StringIO(opening_moves)
        temp_game = chess.pgn.read_game(pgn)
        if not temp_game:
            return []

        opening_mainline_moves = list(temp_game.mainline_moves())

        if opening_mainline_moves:
            last_move = opening_mainline_moves[-1]
            board_before_last_move = temp_game.board()
            for move in opening_mainline_moves[:-1]:
                board_before_last_move.push(move)

            if board_before_last_move.is_castling(last_move):
                king_from_sq = last_move.from_square
                rook_from_sq = chess.H1 if board_before_last_move.is_kingside_castling(last_move) else chess.A1
                if board_before_last_move.turn == chess.BLACK:
                    rook_from_sq = chess.H8 if board_before_last_move.is_kingside_castling(last_move) else chess.A8
                marked_sq_option = f"markfields={{{chess.square_name(king_from_sq)},{chess.square_name(rook_from_sq)}}}"
            else:
                marked_sq_option = f"markfields={{{chess.square_name(last_move.from_square)},{chess.square_name(last_move.to_square)}}}"

        board = temp_game.board()
        for move in opening_mainline_moves:
            board.push(move)
        fen = board.fen()

        temp_board_for_notation = temp_game.board()
        formatted_moves_parts = []
        for i, move in enumerate(opening_mainline_moves):
            if i % 2 == 0:
                formatted_moves_parts.append(f"{(i // 2) + 1}.")

            san = temp_board_for_notation.san(move)
            if notation_type == "figurine":
                piece = temp_board_for_notation.piece_at(move.from_square)
                if piece and piece.piece_type != chess.PAWN:
                    figurine_cmd = _get_chess_figurine(piece.symbol())
                    san_suffix = san[1:] if san and san[0].upper() in 'NBRQK' else san
                    formatted_moves_parts.append(figurine_cmd + escape_latex_special_chars(san_suffix))
                else:
                    formatted_moves_parts.append(escape_latex_special_chars(san))
            else:  # algebraic
                formatted_moves_parts.append(escape_latex_special_chars(translate_san_move(san)))

            temp_board_for_notation.push(move)

        opening_moves_latex = " ".join(formatted_moves_parts)

    except Exception:
        fen = chess.Board().fen()
        opening_moves_latex = escape_latex_special_chars(opening_moves)

    # --- Setup for the new layout ---
    if args:
        board_size = PAPER_SIZE_SETTINGS[args.paper_size]['board_size']
        board_size_option = f"boardfontsize={board_size}"
    else:
        board_size_option = "tinyboard"  # Fallback

    board_options = [
        f"setfen={{{fen}}}",
        board_size_option,
        "showmover=false",
        "linewidth=0.1em",
        "pgfstyle=border"
    ]
    if marked_sq_option:
        board_options.append(marked_sq_option)
    options_str = ", ".join(board_options)
    chessboard_cmd = f"\\chessboard[{options_str}]"

    # Use a \parbox to force left alignment within the first column.
    # The opening name is now wrapped in \textbf{...} to make it bold.
    opening_name_latex = f"\\textbf{{{escape_latex_special_chars(opening_name)}}}"
    eco_code_latex = escape_latex_special_chars(f"({eco_code})")
    title_latex = f"{opening_name_latex} {eco_code_latex}"

    left_cell_content = (
        fr"\parbox[t]{{\linewidth}}{{\raggedright {title_latex}\\[0.5ex] {opening_moves_latex}}}"
    )

    # Use a standard tabularx; the parbox handles the alignment.
    latex_lines.append(r"\begin{tabularx}{\linewidth}{X X}")
    latex_lines.append(f"{left_cell_content} &")
    latex_lines.append(fr"\centering {chessboard_cmd} \\")
    latex_lines.append(r"\end{tabularx}")

    return latex_lines


def _generate_game_notation_latex(game, notation_type, lang='en', annotated=False):
    """
    Generates the LaTeX for the game notation. For long games, it uses a two-column
    tabbing environment for perfect alignment and minimal spacing.
    """
    footnote = ""
    if annotated:
        key = 'fn_notation_figurine' if notation_type == 'figurine' else 'fn_notation_algebraic'
        footnote = f"\\footnote{{{MESSAGES[key]}}}"

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
                # Apply translation for algebraic notation
                if notation_type == "algebraic":
                    san = translate_san_move(san)

                if notation_type == "figurine":
                    # For promotions, use the translated algebraic notation as per convention.
                    if move.promotion:
                        return escape_latex_special_chars(translate_san_move(san))

                    # For all other moves, use the standard figurine logic.
                    piece = temp_board.piece_at(move.from_square)
                    if piece and piece.piece_type != chess.PAWN:
                        figurine_cmd = _get_chess_figurine(piece.symbol())
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
                if white_move.promotion:
                    white_move_str_latex = escape_latex_special_chars(translate_san_move(white_san))
                else:
                    moving_piece = board.piece_at(white_move.from_square)
                    if moving_piece and moving_piece.piece_type != chess.PAWN:
                        figurine_cmd = _get_chess_figurine(moving_piece.symbol())
                        san_suffix = white_san[1:] if white_san and white_san[0].upper() in 'NBRQK' else white_san
                        white_move_str_latex = figurine_cmd + escape_latex_special_chars(san_suffix)
                    else:
                        white_move_str_latex = escape_latex_special_chars(white_san)
            else:
                white_move_str_latex = escape_latex_special_chars(translate_san_move(white_san))
            board.push(white_move)

            black_move_str_latex = ""
            if (i + 1) < len(moves):
                black_move = moves[i + 1]
                black_san = board.san(black_move)
                # Apply translation for algebraic notation
                if notation_type == "algebraic":
                    black_san = translate_san_move(black_san)

                if notation_type == "figurine":
                    if black_move.promotion:
                        black_move_str_latex = escape_latex_special_chars(translate_san_move(black_san))
                    else:
                        moving_piece = board.piece_at(black_move.from_square)
                        if moving_piece and moving_piece.piece_type != chess.PAWN:
                            figurine_cmd = _get_chess_figurine(moving_piece.symbol())
                            san_suffix = black_san[1:] if black_san and black_san[0].upper() in 'NBRQK' else black_san
                            black_move_str_latex = figurine_cmd + escape_latex_special_chars(san_suffix)
                        else:
                            black_move_str_latex = escape_latex_special_chars(translate_san_move(black_san))
                else:
                    black_move_str_latex = escape_latex_special_chars(translate_san_move(black_san))
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
    header = game.headers.get("Event", MESSAGES['game_event_default'])
    white = game.headers.get("White", MESSAGES['white_player_default'])
    black = game.headers.get("Black", MESSAGES['black_player_default'])
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
    fn = lambda key: f"\\footnote{{{MESSAGES[key]}}}" if annotated else ""
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
    header_white = f"\\textbf{{{MESSAGES['table_white']}}}"
    header_black = f"\\textbf{{{MESSAGES['table_black']}}}"
    avg_cpl_label = MESSAGES['table_avg_cpl']
    latex_lines.append(r"\begin{tabularx}{\linewidth}{l c c}")
    latex_lines.append(f"{header_metric} & {header_white} & {header_black} \\\\ \\cline{{1-1}} \\cline{{2-3}}")
    latex_lines.append(f"{avg_cpl_label} & {white_avg_cpl:.2f} & {black_avg_cpl:.2f} \\\\")
    latex_lines.append(f"{MESSAGES['table_blunders']} & {white_blunders} & {black_blunders} \\\\")
    latex_lines.append(f"{MESSAGES['table_mistakes']} & {white_mistakes} & {black_mistakes} \\\\")
    latex_lines.append(f"{MESSAGES['table_inaccuracies']} & {white_inaccuracies} & {black_inaccuracies} \\\\")
    latex_lines.append(r"\end{tabularx}")

    # Add a single line of vertical space after the table
    latex_lines.append(r"\vspace{\baselineskip}")

    return latex_lines


def _generate_board_analysis_latex(game, analysis_data, show_mover, board_scope, lang='en', annotated=False, args=None):
    """
    Generates the LaTeX for move-by-move board displays, with correctly placed footnotes and check/checkmate markers.
    """
    fn = lambda key: f"\\protect\\footnote{{{MESSAGES[key]}}}" if annotated else ""
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
    for i, (move_text_raw, fen1, marked_sq1, king_mark_opts1, white_analysis, fen2, marked_sq2, king_mark_opts2,
            black_analysis, _, white_node,
            black_node) in enumerate(move_pairs_to_display):

        # Split the raw SAN move text (e.g., "1. Nf3 Nc6") into parts for translation
        move_parts = move_text_raw.split()
        if len(move_parts) > 1:
            move_parts[1] = translate_san_move(move_parts[1])  # Translate White's move
        if len(move_parts) > 2:
            move_parts[2] = translate_san_move(move_parts[2])  # Translate Black's move

        move_text = " ".join(move_parts)

        move_title_footnote = fn('fn_move_reminder') if i == 0 and annotated else ""
        latex_lines.append(f"\\subsubsection*{{{move_text}{move_title_footnote}}}")

        deferred_footnotetexts = []

        board_footnote_mark = ""
        if i == 0 and annotated:
            board_footnote_mark = "\\footnotemark "
            key = 'fn_board_diagram_smart' if board_scope == 'smart' else 'fn_board_diagram_all'
            deferred_footnotetexts.append(f"\\footnotetext{{{MESSAGES[key]}}}")

        analysis_footnote_mark = ""
        if i == 0 and annotated and (white_analysis or black_analysis):
            analysis_footnote_mark = "\\footnotemark "
            deferred_footnotetexts.append(f"\\footnotetext{{{MESSAGES['fn_analysis_explanation']}}}")

        def format_analysis(analysis, node):
            if not analysis:
                return "", ""

            comment_footnote_mark = ""
            comment = node.comment if node and node.comment and not node.comment.strip().startswith('[%') else None
            if comment:
                comment_footnote_mark = "\\footnotemark "
                deferred_footnotetexts.append(f"\\footnotetext{{{escape_latex_special_chars(comment)}}}")

            eval_str = f"\\textit{{{MESSAGES['eval_text']} {get_eval_string(analysis['eval_after_played_move'], lang)}}}"

            if analysis['played_move'] != analysis['engine_best_move_from_pos'] and not analysis[
                'engine_eval_before_played_move'].is_mate():
                loss_str = f"\\textit{{{MESSAGES['loss_text']} {analysis['cpl_for_move']}}}{MESSAGES['cp_text']}"
                classification = classify_move_loss(analysis['cpl_for_move'], lang)
                best_move_str = f"\\textit{{{MESSAGES['best_move_text']} {escape_latex_special_chars(analysis['engine_best_move_from_pos'].uci())}}}"
                separator = "\\text{\\textbar}"
                line1 = f"{comment_footnote_mark}{eval_str} {separator} {loss_str}"
                line2 = f"{classification} ({best_move_str})"
                return line1, line2
            else:
                line1 = f"{comment_footnote_mark}{eval_str} (\\textit{{{MESSAGES['best_move_played_text']}}})"
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
    fn = lambda key: f"\\footnote{{{MESSAGES[key]}}}" if annotated else ""
    latex_lines = []
    white = game.headers.get("White", MESSAGES['white_player_default'])
    black = game.headers.get("Black", MESSAGES['black_player_default'])
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
    message_template = MESSAGES.get(reason_key, "")

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
    latex.extend(_generate_opening_info_latex(game, args.notation_type, lang, annotated=annotated, args=args))

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
    title = MESSAGES['how_to_read_title']

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


def delete_output_directory(output_dir_path, lang='en'):
    """Deletes the output directory if it exists."""
    output_dir = Path(output_dir_path)
    if output_dir.exists() and output_dir.is_dir():
        print(MESSAGES['deleting_output_dir'].format(output_dir=output_dir))
        try:
            shutil.rmtree(output_dir)
        except OSError as e:
            print(MESSAGES['error_deleting_dir'].format(output_dir=output_dir, error_msg=e), file=sys.stderr)
            sys.exit(1)


def compile_latex_to_pdf(output_dir_path, main_tex_file="chess_book.tex", lang='en'):
    """Compiles the LaTeX files to PDF and cleans up auxiliary files."""
    output_dir = Path(output_dir_path)
    main_tex_path = output_dir / main_tex_file
    if not main_tex_path.exists():
        print(MESSAGES['main_latex_not_found'].format(main_tex_file=main_tex_path), file=sys.stderr)
        return
    print(MESSAGES['compiling_latex'].format(output_dir=output_dir))
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
                print(MESSAGES['latex_compile_failed'].format(pass_num=i + 1), file=sys.stderr)
                print(result.stdout, file=sys.stderr)
                print(result.stderr, file=sys.stderr)
        except FileNotFoundError:
            print(MESSAGES['pdflatex_not_found'], file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(MESSAGES['unexpected_latex_error'].format(error_msg=e), file=sys.stderr)
            sys.exit(1)
    print(MESSAGES['latex_compile_complete'])
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
                print(MESSAGES['error_reading_front_matter_page'].format(path=content_path, e=e), file=sys.stderr)
        else:
            print(MESSAGES['front_matter_page_file_not_found'].format(path=content_path), file=sys.stderr)


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
    """Formats raw text for a dedication or epigraph page (centered)."""
    # Escape special characters first
    content_processed = escape_latex_special_chars(content)

    # Respect paragraph breaks from the source text file
    paragraphs = content_processed.strip().split('\n\n')
    # Join paragraphs with a LaTeX paragraph break that includes some vertical space
    content_processed = r"\par\vspace{1\baselineskip}\par ".join(paragraphs)
    # Replace single newlines within a paragraph with a LaTeX line break
    content_processed = content_processed.replace('\n', r" \\ ")

    return (
            r"\cleardoublepage" + "\n" +
            r"\thispagestyle{empty}" + "\n" +
            r"\vspace*{\stretch{1}}" + "\n" +  # Flexible space above the content
            r"\begin{center}" + "\n" +
            fr"\large" + "\n" +  # Use a slightly larger font for style
            content_processed + "\n" +
            r"\end{center}" + "\n" +
            r"\vspace*{\stretch{1}}" + "\n"  # Flexible space below the content
    )


def _format_preface_txt(content, lang):
    """Formats raw text for a preface page (justified with a title)."""
    title = MESSAGES['preface']

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


def _parse_cover_metadata(cover_content):
    """Parses a LaTeX string to find \booktitle, \booksubtitle, and \bookauthor commands."""
    metadata = {}
    patterns = {
        'title': re.compile(r'\\booktitle\{(.*?)\}', re.DOTALL),
        'subtitle': re.compile(r'\\booksubtitle\{(.*?)\}', re.DOTALL),
        'author': re.compile(r'\\bookauthor\{(.*?)\}', re.DOTALL),
    }
    for key, pattern in patterns.items():
        match = pattern.search(cover_content)
        if match:
            metadata[key] = match.group(1).strip()
    return metadata


def _generate_simple_title_page(title, subtitle, author):
    """Generates a simple, clean title page from strings."""
    title_latex = f"{{\\Huge \\bfseries {escape_latex_special_chars(title)}}}" if title else ""
    subtitle_latex = f"{{\\Large \\itshape {escape_latex_special_chars(subtitle)}}}" if subtitle else ""
    author_latex = f"{{\\Large {escape_latex_special_chars(author)}}}" if author else ""

    separator = r"\\ \vspace{0.5cm}" if title and subtitle else ""

    # Define the chess symbol to be placed in the middle of the page
    knight_symbol = r"\resizebox{!}{3cm}{{\WhiteKnightOnBlack}}"

    return dedent(fr'''
        \begin{{titlepage}}
            \thispagestyle{{empty}}
            \centering
            \vspace*{{4cm}}
            {title_latex}
            {separator}
            {subtitle_latex}
            \vfill
            {knight_symbol}
            \vfill
            {author_latex}
            \vspace*{{2cm}}
        \end{{titlepage}}
    ''')


def _generate_notation_appendix(notation_type, lang='en'):
    """
    Generates a unified LaTeX appendix explaining chess notation, with comprehensive examples.
    """
    msg = MESSAGES
    title = msg['appendix_notation_title']
    intro = msg['appendix_intro']
    special_moves_title = msg['appendix_special_moves']
    subtitle = msg['appendix_combined_subtitle']

    # Dynamically create example notations
    knight_letter = msg['piece_letters'].get('N', 'N')
    queen_letter = msg['piece_letters'].get('Q', 'Q')
    knight_figurine = _get_chess_figurine('N')
    queen_figurine = _get_chess_figurine('Q')

    # Format each example using the loaded message templates
    ex_move = msg['appendix_example_move'].format(algebraic=f"{knight_letter}f3", figurine=f"{knight_figurine}f3")
    ex_capture = msg['appendix_example_capture'].format(algebraic=f"{knight_letter}xf3", figurine=f"{knight_figurine}xf3")
    ex_k_castle = msg['appendix_example_kingside_castle']
    ex_q_castle = msg['appendix_example_queenside_castle']
    ex_promo = msg['appendix_example_promotion'].format(algebraic=f"e8={queen_letter}", figurine=f"e8={queen_figurine}")
    ex_check = msg['appendix_example_check'].format(algebraic=f"{queen_letter}h5", figurine=f"{queen_figurine}h5")
    ex_mate = msg['appendix_example_checkmate'].format(algebraic=f"{queen_letter}h7", figurine=f"{queen_figurine}h7")

    piece_table = dedent(fr'''
        \begin{{tabular}}{{l c c}}
        \textbf{{{msg['appendix_table_piece']}}} & \textbf{{{msg['appendix_table_symbol_san']}}} & \textbf{{{msg['appendix_table_symbol_fan']}}} \\ \hline
        {msg['appendix_table_king']} & {MESSAGES['piece_letters'].get('K', 'K')} & {_get_chess_figurine('K')} / {_get_chess_figurine('k')} \\
        {msg['appendix_table_queen']} & {MESSAGES['piece_letters'].get('Q', 'Q')} & {_get_chess_figurine('Q')} / {_get_chess_figurine('q')} \\
        {msg['appendix_table_rook']} & {MESSAGES['piece_letters'].get('R', 'R')} & {_get_chess_figurine('R')} / {_get_chess_figurine('r')} \\
        {msg['appendix_table_bishop']} & {MESSAGES['piece_letters'].get('B', 'B')} & {_get_chess_figurine('B')} / {_get_chess_figurine('b')} \\
        {msg['appendix_table_knight']} & {MESSAGES['piece_letters'].get('N', 'N')} & {_get_chess_figurine('N')} / {_get_chess_figurine('n')} \\
        \multicolumn{{3}}{{l}}{{{msg['appendix_table_pawn']}}} \\
        \end{{tabular}}
    ''')

    return dedent(fr'''
        \newpage
        \section*{{{''}}}
        \addcontentsline{{toc}}{{section}}{{{title}}}
        \markright{{{title}}}
        \thispagestyle{{fancy}}

        \subsection*{{{subtitle}}}
        {intro}

        \smallskip
        \begin{{center}}
        \chessboard[tinyboard, showmover=false]
        \end{{center}}
        \smallskip

        \subsubsection*{{{msg['appendix_piece_names']}}}
        {piece_table}

        \subsubsection*{{{special_moves_title}}}
        \begin{{itemize}}[leftmargin=*, noitemsep, topsep=0.5ex]
            \item {msg['appendix_capture_text']}
            \item {msg['appendix_en_passant_text']}
            \item {msg['appendix_check_text']}
            \item {msg['appendix_castling_text']}
            \item {msg['appendix_promotion_text']}
            \item {msg['appendix_disambiguation']}
        \end{{itemize}}
        
        \newpage

        \subsubsection*{{{msg['appendix_examples_title']}}}
        \begin{{itemize}}[leftmargin=*, noitemsep, topsep=0.5ex]
            \item {ex_move}
            \item {ex_capture}
            \item {ex_k_castle}
            \item {ex_q_castle}
            \item {ex_promo}
            \item {ex_check}
            \item {ex_mate}
        \end{{itemize}}
    ''')


def _generate_time_controls_explanation_latex(time_controls, lang='en'):
    """
    Generates a LaTeX page explaining the time controls found in the PGN.
    """
    msg = MESSAGES
    title = msg['time_controls_title']

    # Format the list of unique time controls for display
    formatted_tc_list = ", ".join([f"\\texttt{{{tc}}}" for tc in sorted(list(time_controls))])

    return dedent(fr'''
        \newpage
        \section*{{{title}}}
        \addcontentsline{{toc}}{{section}}{{{title}}}
        \markright{{{title}}}
        \thispagestyle{{fancy}}

        {msg['time_controls_intro']}
        \begin{{itemize}}[leftmargin=*]
            \item {msg['time_controls_increment_desc']}
            \item {msg['time_controls_standard_desc']}
            \item {msg['time_controls_daily_desc']}
        \end{{itemize}}

        \subsection*{{{msg['time_controls_list_title']}}}
        {formatted_tc_list}
    ''')


def _generate_final_page():
    """Generates a final, clean page with a large king symbol."""
    # Define the chess symbol to be placed on the page
    king_symbol = r"\resizebox{!}{3cm}{{\WhiteKingOnBlack}}"

    return dedent(fr'''
        \newpage\thispagestyle{{empty}}\mbox{{}}
        \cleardoublepage
        \thispagestyle{{empty}}
        \vspace*{{\stretch{{1}}}}
        \begin{{center}}
        {king_symbol}
        \end{{center}}
        \vspace*{{\stretch{{2}}}}
    ''')


def _process_book_part(directory, basename, lang):
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
            return _format_preface_txt(content, lang)
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

    # --- Extract unique time controls from the games ---
    unique_time_controls = set(game.headers.get("TimeControl", "?") for game in games)

    settings = PAPER_SIZE_SETTINGS[args.paper_size]

    # --- Process Book Design and Metadata ---
    design_dir = args.book_design_dir
    book_metadata = {}
    front_cover_content = ""
    cover_file_path, _ = _find_book_part_file(design_dir, "front-cover")

    if cover_file_path:
        print("Found front cover file, parsing for metadata...")
        front_cover_content = cover_file_path.read_text(encoding='utf-8')
        book_metadata = _parse_cover_metadata(front_cover_content)

    # Fallback to CLI options if metadata not in cover file
    title = book_metadata.get('title', args.title)
    subtitle = book_metadata.get('subtitle', args.subtitle)
    author = book_metadata.get('author', args.author)

    dedication_content = _process_book_part(design_dir, "dedication", args.language)
    epigraph_content = _process_book_part(design_dir, "epigraph", args.language)
    preface_content = _process_book_part(design_dir, "preface", args.language)
    back_cover_content = _process_book_part(design_dir, "back-cover", args.language)

    # Check if any front matter content was actually loaded.
    has_front_matter = any([front_cover_content, dedication_content, epigraph_content, preface_content])

    # --- Assemble the Book ---
    tex_master = []
    tex_master.append(f"\\renewcommand{{\\contentsname}}{{{MESSAGES['toc_title']}}}")
    tex_master.append(get_latex_header_part1(settings))

    # Define book metadata commands for use in the document
    tex_master.append(f"\\newcommand{{\\booktitle}}{{{escape_latex_special_chars(title)}}}")
    tex_master.append(f"\\newcommand{{\\booksubtitle}}{{{escape_latex_special_chars(subtitle)}}}")
    tex_master.append(f"\\newcommand{{\\bookauthor}}{{{escape_latex_special_chars(author)}}}")

    # Switch to frontmatter mode and set the page style to empty for this section.
    tex_master.append(r"\frontmatter")
    tex_master.append(r"\pagestyle{empty}")

    if front_cover_content:
        tex_master.append(front_cover_content)

    # Add a blank page
    if has_front_matter:
        tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")

    # Generate a simple title page if no front cover was provided but title/author info exists
    if not front_cover_content and (title or subtitle or author):
        tex_master.append(_generate_simple_title_page(title, subtitle, author))
        tex_master.append(r"\cleardoublepage")

    # Ensure dedication, epigraph, TOC, and preface start on an odd page.
    if dedication_content:
        tex_master.append(r"\cleardoublepage")
        tex_master.append(dedication_content)
    if epigraph_content:
        tex_master.append(r"\cleardoublepage")
        tex_master.append(epigraph_content)

    tex_master.append(r"\cleardoublepage")

    # Switch to mainmatter mode. This resets the page number to 1 (Arabic).
    tex_master.append(r"\mainmatter")
    # Restore the default 'fancy' page style for the rest of the book.
    tex_master.append(r"\pagestyle{fancy}")

    tex_master.append(LATEX_HEADER_PART2_TOC)

    if preface_content:
        tex_master.append(preface_content)

    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        engine.configure({"Threads": 2, "Hash": 128})
    except Exception as e:
        print(MESSAGES['error_starting_stockfish'].format(e=e, ENGINE_PATH=ENGINE_PATH))
        print(MESSAGES['analysis_disabled_warning'])

    if args.how_to_read:
        generate_how_to_read_section(tex_master, args, output_dir, engine)
        tex_master.append(_generate_notation_appendix(args.notation_type, args.language))
        tex_master.append(_generate_time_controls_explanation_latex(unique_time_controls, args.language))

    tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")
    tex_master.append(r"\cleardoublepage")

    for idx, game in enumerate(games):
        try:
            print(MESSAGES['exporting_game'].format(current_game=idx + 1, total_games=len(games)))
            analysis_data = []
            if engine:
                analysis_data = analyze_game_with_stockfish(game, engine)
            else:
                print(MESSAGES['skipping_stockfish_analysis'].format(game_num=idx + 1))

            export_game_to_latex(
                game, idx + 1, output_dir, analysis_data, args
            )
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(MESSAGES['skipping_game_error'].format(game_num=idx + 1, error_msg=e))

    tex_master.append(r"\cleardoublepage")

    # The backmatter command is useful for appendices, indices, etc.
    tex_master.append(r"\backmatter")

    tex_master.append(_generate_final_page())

    # Add a blank page if there is front matter.
    if has_front_matter:
        tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")
        tex_master.append(r"\newpage\thispagestyle{empty}\mbox{}")

    # Back Cover at the very end
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
    parser.add_argument("output_dir", type=str,
                        help="Directory where the LaTeX files and the final PDF will be generated.")
    parser.add_argument("--book_design_dir", type=str,
                        help="Directory containing LaTeX/text files for book parts (front-cover, dedication, etc.).")
    parser.add_argument("--title", type=str,
                        help="The title of the book (optional).")
    parser.add_argument("--subtitle", type=str,
                        help="The subtitle of the book (optional).")
    parser.add_argument("--author", type=str,
                        help="The author of the book (optional).")
    parser.add_argument("--notation_type", type=str, choices=["algebraic", "figurine"], default="figurine",
                        help="Type of notation to use: 'algebraic' or 'figurine' (default: 'figurine').")
    parser.add_argument("--display_boards", action="store_true",
                        help="Enable display of chessboards. If off (default), only notation is displayed.")
    parser.add_argument("--board_scope", type=str, choices=["all", "smart"], default="smart",
                        help="Specify whether to display boards for 'all' moves or only 'smart' moves (i.e., moves with CPL > 0, default: 'smart').")
    parser.add_argument("--language", type=str, choices=["en", "fr"], default="en", help="Language for text.")
    parser.add_argument("--paper_size", type=str, choices=['a3', 'a4', 'a5'], default='a4',
                        help="Paper size for the output PDF (default: 'a4').")
    parser.add_argument("--how_to_read", action="store_true", help="Add 'How to Read This Book' section.")
    args = parser.parse_args()

    # Load the messages right after parsing arguments
    load_messages(args.language)
    load_openings()

    delete_output_directory(args.output_dir, args.language)
    generate_chess_book(args)
    compile_latex_to_pdf(args.output_dir, lang=args.language)