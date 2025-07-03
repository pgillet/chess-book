import sys
from pathlib import Path
from textwrap import dedent
import argparse

import chess.engine
import chess.pgn

ENGINE_PATH = "/opt/homebrew/bin/stockfish"  # Update if necessary
MAX_BOARDS_PER_PAGE = 6  # This is a guideline for layout, not a strict page break trigger now

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

LATEX_HEADER = dedent(r'''
    \documentclass[10pt]{book}
    \usepackage[margin=0.7in]{geometry}
    \usepackage{chessboard}
    \usepackage{multicol}
    \usepackage{fancyhdr}
    \usepackage{titlesec}
    \usepackage{parskip}
    \usepackage{tabularx}
    \usepackage{skak}
    \usepackage{scalerel}
    %\usepackage{fontspec} % Required for Unicode fonts like those used by utfsym
    % \usepackage{utfsym} % For \usym command to display Unicode symbols
    % Redefine tabularxcolumn for vertical centering within X columns
    \renewcommand{\tabularxcolumn}[1]{m{#1}}

    % Remove numbering from sections
    \titleformat{\section}{\normalfont\Large\bfseries}{}{0pt}{}
    \setlength{\parindent}{0pt}

    % Redefine \sectionmark to show only the section title without numbering
    \renewcommand{\sectionmark}[1]{\markright{#1}}

    \pagestyle{fancy}
    \fancyhf{} % Clear all headers and footers first
    \renewcommand{\headrulewidth}{0pt} % Remove the horizontal header line

    % Define the header for odd pages (right-hand pages)
    \fancyhead[RO]{\nouppercase{\rightmark}} % Right Odd: Show the current section title

    % Define the footer for even pages (left-hand pages)
    \fancyfoot[LE,RO]{\thepage} % Left Even, Right Odd
    % Define the footer for odd pages (right-hand pages)
    \fancyfoot[LO,CE]{} % Left Odd, Center Even

    % Redefine the plain page style (used for chapter pages)
    \fancypagestyle{plain}{
        \fancyhf{} % Clear all header and footer fields
        \fancyfoot[LE,RO]{\thepage} % Page numbers on the bottom left for even pages and bottom right for odd pages
        \renewcommand{\headrulewidth}{0pt} % Ensure the horizontal line is removed on plain pages as well
    }

    % IMPORTANT: You might need to install the 'utfsym' package if you don't have it.
    % Also, ensure you have a font installed on your system that contains Unicode chess symbols.
    % Common examples for a font that works well with utfsym:
    % 'Noto Serif Chess', 'Segoe UI Symbol' (on Windows), 'Symbola', 'Chess Alpha'.
    % If your font needs to be explicitly set for utfsym, uncomment and modify
    % the line below, replacing 'Your Chess Unicode Font Name' with the exact name
    % of the font installed on your system:
    % \setmainfont{Your Chess Unicode Font Name}
    \begin{document}
    \tableofcontents % Generates the Table of Contents
    \newpage % Starts the main content on a new page after the TOC
''')

LATEX_FOOTER = "\\end{document}"


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


def is_tactical(board, move):
    return board.is_capture(move) or board.gives_check(move)


def find_smart_moves(game):
    smart_moves = set()
    try:
        with chess.engine.SimpleEngine.popen_uci(ENGINE_PATH) as engine:
            board = game.board()
            for i, move in enumerate(game.mainline_moves()):
                info = engine.analyse(board, chess.engine.Limit(depth=15))
                best = info["pv"][0]
                if best != move:
                    smart_moves.add(i)
                board.push(move)
    except Exception as e:
        print(f"⚠️ Engine analysis failed: {e}")
    return smart_moves


def _get_chess_figurine(piece_symbol, default_value="", inline=True):
    if inline:
        figurine_cmd = INLINE_CHESS_SYMBOL.get(piece_symbol, default_value)
        figurine_cmd = "\scalerel*{" + figurine_cmd + "}{Xg}"
    else:
        figurine_cmd = UNICODE_CHESS_SYMBOL.get(piece_symbol, default_value)

    return figurine_cmd


def _generate_game_notation_latex(game, notation_type):
    notation_lines = []
    board = game.board()
    moves = list(game.mainline_moves())

    notation_lines.append("\\noindent")
    # Use tabularx for aligned columns:
    # l: left-aligned column for move number
    # l: left-aligned column for White's move
    # l: left-aligned column for Black's move
    notation_lines.append("\\begin{tabularx}{\\linewidth}{l l l}")

    for i in range(0, len(moves), 2):  # Iterate through moves in pairs (White's move index)
        move_number = (i // 2) + 1

        # White's move
        white_move_str_latex = ""
        white_move = moves[i]
        white_san = board.san(white_move)

        if notation_type == "figurine":
            moving_piece = board.piece_at(white_move.from_square)
            if moving_piece and moving_piece.piece_type != chess.PAWN:
                piece_symbol = moving_piece.symbol()
                figurine_cmd = _get_chess_figurine(piece_symbol)
                if white_san and white_san[0].upper() in 'NBRQK':
                    white_move_str_latex = figurine_cmd + " " + escape_latex_special_chars(white_san[1:])
                else:
                    white_move_str_latex = escape_latex_special_chars(white_san)
            else:
                white_move_str_latex = escape_latex_special_chars(white_san)
        else:  # Algebraic
            white_move_str_latex = escape_latex_special_chars(white_san)

        board.push(white_move)  # Apply White's move to board

        # Black's move (if exists)
        black_move_str_latex = ""
        if (i + 1) < len(moves):
            black_move = moves[i + 1]
            black_san = board.san(black_move)

            if notation_type == "figurine":
                moving_piece = board.piece_at(black_move.from_square)
                if moving_piece and moving_piece.piece_type != chess.PAWN:
                    piece_symbol = moving_piece.symbol()
                    figurine_cmd = _get_chess_figurine(piece_symbol)
                    if black_san and black_san[0].upper() in 'NBRQK':
                        black_move_str_latex = figurine_cmd + " " + escape_latex_special_chars(black_san[1:])
                    else:
                        black_move_str_latex = escape_latex_special_chars(black_san)
                else:
                    black_move_str_latex = escape_latex_special_chars(black_san)
            else:  # Algebraic
                black_move_str_latex = escape_latex_special_chars(black_san)

            board.push(black_move)  # Apply Black's move to board

        # Construct the LaTeX row for this move pair using & for column separation
        notation_lines.append(f"{move_number}. & {white_move_str_latex} & {black_move_str_latex}\\\\")

    notation_lines.append("\\end{tabularx}")  # End the tabularx environment
    notation_lines.append("\\vspace{1ex}")

    return notation_lines


def export_game_to_latex(game, game_index, output_dir, smart_moves, notation_type, show_mover=False):
    latex = []
    board = game.board()  # This board will be advanced to get FEN *after* each move
    moves = list(game.mainline_moves())

    # Game metadata
    header = game.headers.get("Event", f"Game {game_index}")
    white = game.headers.get("White", "White")
    black = game.headers.get("Black", "Black")
    result = game.headers.get("Result", "*")

    white_escaped = escape_latex_special_chars(white)
    black_escaped = escape_latex_special_chars(black)
    header_escaped = escape_latex_special_chars(header)

    latex.append("\\newpage")  # Always start a new game on a new page
    latex.append(f"\\section{{{white_escaped} vs {black_escaped} ({result}) - {header_escaped}}}")

    latex.extend(_generate_game_notation_latex(game, notation_type))

    move_pairs_to_display = []  # Stores (move_text, fen_after_white_move, marked_squares_white, fen_after_black_move, marked_squares_black)

    temp_board_for_fen = game.board()  # Use this board to track position and generate FENs
    for i in range(0, len(moves), 2):  # Iterate in steps of 2 (White and Black move pairs)
        current_move_pair_text = f"{(i // 2) + 1}."

        fen1, marked_sq1 = "", ""
        fen2, marked_sq2 = "", ""
        is_smart_pair = False

        # White move
        if i < len(moves):
            white_move_obj = moves[i]
            current_move_pair_text += f" {escape_latex_special_chars(temp_board_for_fen.san(white_move_obj))}"
            temp_board_for_fen.push(white_move_obj)
            fen1 = temp_board_for_fen.board_fen()
            marked_sq1 = f"{{ {chess.square_name(white_move_obj.from_square)}, {chess.square_name(white_move_obj.to_square)} }}"
            if i in smart_moves:
                is_smart_pair = True

        # Black move
        if (i + 1) < len(moves):
            black_move_obj = moves[i + 1]
            current_move_pair_text += f" {escape_latex_special_chars(temp_board_for_fen.san(black_move_obj))}"
            temp_board_for_fen.push(black_move_obj)
            fen2 = temp_board_for_fen.board_fen()
            marked_sq2 = f"{{ {chess.square_name(black_move_obj.from_square)}, {chess.square_name(black_move_obj.to_square)} }}"
            if (i + 1) in smart_moves:
                is_smart_pair = True
        else:
            # If only a white move in the last pair, fill black's data with the same board state and no marked squares
            fen2 = fen1  # Use the same FEN as white's board for the second slot if no black move
            marked_sq2 = ""  # No black move, so no squares to mark

        if is_smart_pair:
            move_pairs_to_display.append((
                current_move_pair_text,
                fen1, marked_sq1,
                fen2, marked_sq2
            ))

    # Now, iterate through the collected smart move pairs and generate LaTeX
    for i, (move_text, fen1, marked_sq1, fen2, marked_sq2) in enumerate(move_pairs_to_display):
        latex.append(r"\begin{minipage}{\linewidth}")
        latex.append(f"\\textbf{{{move_text}}} \\\\[0.5ex]")
        latex.append("\\begin{tabularx}{\\linewidth}{X X}")

        # White's move board (state AFTER White's move)
        latex.append(
            f"\\chessboard[setfen={{ {fen1} }}, boardfontsize=20pt, mover=b, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, markfields={marked_sq1}] &")
        # Black's move board (state AFTER Black's move)
        latex.append(
            f"\\chessboard[setfen={{ {fen2} }}, boardfontsize=20pt, mover=w, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, markfields={marked_sq2}] \\\\")

        latex.append("\\end{tabularx}")
        latex.append("\\vspace{2ex}")  # Add some vertical space between board pairs
        latex.append(r"\end{minipage}")

    game_file = output_dir / f"game_{game_index:03}.tex"
    with open(game_file, "w") as f:
        f.write("\n".join(latex))


def generate_chess_book(pgn_path, output_dir_path, notation_type="figurine"):
    pgn_path = Path(pgn_path)
    output_dir = Path(output_dir_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(pgn_path) as f:
        games = []
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            games.append(game)

    tex_master = [LATEX_HEADER]
    for idx, game in enumerate(games):
        try:
            print(f"Export game {idx + 1}/{len(games)} to LaTeX")
            smart_moves = find_smart_moves(game)
            export_game_to_latex(game, idx + 1, output_dir, smart_moves, notation_type)
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(f"⚠️ Skipping corrupted game {idx + 1}: {e}")

    tex_master.append(LATEX_FOOTER)
    with open(output_dir / "chess_book.tex", "w") as f:
        f.write("\n".join(tex_master))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a chess book from PGN files."
    )
    parser.add_argument(
        "pgn_file",
        type=str,
        help="Path to the PGN file containing chess games."
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where the LaTeX files and the final PDF will be generated."
    )
    parser.add_argument(
        "--notation_type",
        type=str,
        choices=["algebraic", "figurine"],
        default="figurine",
        help="Type of notation to use: 'algebraic' or 'figurine' (default: 'figurine')."
    )

    args = parser.parse_args()

    generate_chess_book(args.pgn_file, args.output_dir, args.notation_type)