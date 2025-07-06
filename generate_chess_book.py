import sys
from pathlib import Path
from textwrap import dedent
import argparse
import shutil  # For deleting directories
import subprocess  # For running pdflatex

import chess.engine
import chess.pgn

LATEX_COMPILE_PASSES = 1

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
    \renewcommand{\tabularxcolumn}[1]{>{\centering\arraybackslash}m{#1}}

    % Remove numbering from sections AND from TOC entries for sections
    \titleformat{\section}{\normalfont\Large\bfseries}{}{0pt}{}
    \titlespacing{\section}{0pt}{0pt}{0pt}
    \setcounter{secnumdepth}{-1} % This hides section numbers in the TOC as well
    \setcounter{tocdepth}{1} % Ensure sections are included in TOC, but not lower levels by default
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
        \renewcommand{\headrulerulewidth}{0pt} % Ensure the horizontal line is removed on plain pages as well
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


def get_eval_string(score):
    """Formats a Stockfish score object into a human-readable string."""
    if score is None:
        return "N/A"

    # Ensure we are always evaluating from White's perspective for display consistency
    white_pov_score = score.white()

    if white_pov_score.is_mate():
        # If it's a mate, get the mate value from the white_pov_score object
        # Attempt to call mate() as a method, in case it's implemented that way in the user's environment
        mate_value = white_pov_score.mate()
        # Display M0 for mate in 0 (e.g., stalemate or immediate mate from prev move)
        # Use abs() to ensure positive mate distance as per convention.
        return f"M{abs(mate_value)}" if mate_value != 0 else "0"

    # If not mate, convert centipawns to pawns with two decimal places and a sign
    return f"{white_pov_score.cp / 100.0:+.2f}"


def classify_move_loss(cpl):
    """Classifies a move based on Centipawn Loss (CPL)."""
    if cpl >= 200:
        return "\\textbf{Blunder}"
    elif cpl >= 100:
        return "\\textbf{Mistake}"
    elif cpl >= 50:
        return "Inaccuracy"
    return "Good Move"


def analyze_game_with_stockfish(game, engine):
    """
    Analyzes each half-move of a game using Stockfish to get evaluations and CPL.
    Returns a list of dictionaries, where each dict contains analysis data for a half-move.
    """
    analysis_results = []  # Stores data for each half-move
    board = game.board()
    moves = list(game.mainline_moves())

    for i, move in enumerate(moves):
        # Analyze the position *before* the current move
        # This gives us the ideal evaluation if the best move was played from this position.
        analysis_before_move = engine.analyse(board, chess.engine.Limit(depth=15))

        best_move_from_pos = analysis_before_move["pv"][0] if analysis_before_move["pv"] else None
        ideal_eval_before_move = analysis_before_move[
            "score"]  # Evaluation of current position (assuming optimal play from here)

        # Apply the played move to a temporary board to get its outcome evaluation
        temp_board_after_played_move = board.copy()
        temp_board_after_played_move.push(move)
        analysis_after_played_move = engine.analyse(temp_board_after_played_move, chess.engine.Limit(depth=15))
        eval_after_played_move = analysis_after_played_move["score"]

        # Calculate centipawn loss (CPL)
        cpl = 0
        if not ideal_eval_before_move.is_mate() and not eval_after_played_move.is_mate():
            # Get evaluations consistently from White's perspective
            ideal_cp_white_pov = ideal_eval_before_move.white().cp
            played_cp_white_pov = eval_after_played_move.white().cp

            # CPL is how much the evaluation drops for the player whose turn it was
            if board.turn == chess.WHITE:
                cpl = max(0, ideal_cp_white_pov - played_cp_white_pov)
            else:  # Black's turn (higher score for White means worse for Black)
                cpl = max(0, played_cp_white_pov - ideal_cp_white_pov)

        # Store results for the current move
        analysis_results.append({
            'move_index': i,  # 0-indexed half-move number
            'played_move': move,
            'is_white_move': board.turn == chess.WHITE,
            'engine_eval_before_played_move': ideal_eval_before_move,  # Eval of position before the played move
            'engine_best_move_from_pos': best_move_from_pos,
            'eval_after_played_move': eval_after_played_move,  # Eval of position after the played move
            'cpl_for_move': cpl,
        })
        board.push(move)  # Advance board for next iteration

    return analysis_results


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
    notation_lines.append("\\par\\vspace{\\baselineskip}")  # Changed to ensure one line of space

    return notation_lines


def _generate_game_metadata_latex(game, game_index):
    """
    Generates the LaTeX for the game's metadata section (title, players, result).
    """
    latex_lines = []
    header = game.headers.get("Event", f"Game {game_index}")
    white = game.headers.get("White", "White")
    black = game.headers.get("Black", "Black")
    result = game.headers.get("Result", "*")

    white_escaped = escape_latex_special_chars(white)
    black_escaped = escape_latex_special_chars(black)
    header_escaped = escape_latex_special_chars(header)

    latex_lines.append("\\newpage")  # Always start a new game on a new page
    latex_lines.append(f"\\section{{{white_escaped} vs {black_escaped} ({result}) - {header_escaped}}}")
    latex_lines.append("\\par\\vspace{\\baselineskip}")  # Added to ensure one line of space before notation
    return latex_lines


def _generate_analysis_summary_latex(analysis_data):
    """
    Generates the LaTeX for the analysis summary section (CPL, blunders, etc.).
    """
    latex_lines = []
    if not analysis_data:
        return latex_lines  # Return empty if no analysis data

    latex_lines.append(r"\subsection*{Analysis Summary}")

    total_moves_analyzed = len(analysis_data)
    white_moves_count = sum(1 for d in analysis_data if d['is_white_move'])
    black_moves_count = total_moves_analyzed - white_moves_count

    white_total_cpl = sum(d['cpl_for_move'] for d in analysis_data if d['is_white_move'])
    black_total_cpl = sum(d['cpl_for_move'] for d in analysis_data if not d['is_white_move'])

    white_avg_cpl = (white_total_cpl / white_moves_count) if white_moves_count > 0 else 0
    black_avg_cpl = (black_total_cpl / black_moves_count) if black_moves_count > 0 else 0

    white_blunders = sum(1 for d in analysis_data if d['is_white_move'] and d['cpl_for_move'] >= 200)
    black_blunders = sum(1 for d in analysis_data if not d['is_white_move'] and d['cpl_for_move'] >= 200)
    white_mistakes = sum(
        1 for d in analysis_data if d['is_white_move'] and d['cpl_for_move'] >= 100 and d['cpl_for_move'] < 200)
    black_mistakes = sum(
        1 for d in analysis_data if not d['is_white_move'] and d['cpl_for_move'] >= 100 and d['cpl_for_move'] < 200)
    white_inaccuracies = sum(
        1 for d in analysis_data if d['is_white_move'] and d['cpl_for_move'] >= 50 and d['cpl_for_move'] < 100)
    black_inaccuracies = sum(
        1 for d in analysis_data if not d['is_white_move'] and d['cpl_for_move'] >= 50 and d['cpl_for_move'] < 100)

    latex_lines.append(dedent(f"""
        \\begin{{itemize}}
            \\item \\textbf{{Overall Accuracy:}}
            \\begin{{itemize}}
                \\item White Average CPL: {white_avg_cpl:.2f}
                \\item Black Average CPL: {black_avg_cpl:.2f}
            \\end{{itemize}}
            \\item \\textbf{{Mistakes \\& Blunders:}}
            \\begin{{itemize}}
                \\item White: {white_blunders} Blunders, {white_mistakes} Mistakes, {white_inaccuracies} Inaccuracies
                \\item Black: {black_blunders} Blunders, {black_mistakes} Mistakes, {black_inaccuracies} Inaccuracies
            \\end{{itemize}}
        \\end{{itemize}}
        \\par\\vspace{{\\baselineskip}}
    """))
    return latex_lines


def _generate_board_analysis_latex(game, analysis_data, show_mover, board_scope):
    """
    Generates the LaTeX for move-by-move board displays and their analysis.
    """
    latex_lines = []
    if not analysis_data:
        return latex_lines  # Return empty if no analysis data

    # Create a new board for displaying positions, starting from the game's initial position
    board_for_display = game.board()
    moves_list = list(game.mainline_moves())

    # Stores (move_text, fen_after_white_move, marked_squares_white, white_analysis_data,
    #          fen_after_black_move, marked_squares_black, black_analysis_data,
    #          has_cpl_in_pair)
    all_calculated_move_pairs = []

    for i in range(0, len(moves_list), 2):  # Iterate in steps of 2 (White and Black move pairs)
        current_move_pair_text = f"{(i // 2) + 1}."

        fen1, marked_sq1 = "", ""
        fen2, marked_sq2 = "", ""

        white_move_obj = moves_list[i] if i < len(moves_list) else None
        black_move_obj = moves_list[i + 1] if (i + 1) < len(moves_list) else None

        white_analysis_data = analysis_data[i] if white_move_obj and i < len(analysis_data) else None
        black_analysis_data = analysis_data[i + 1] if black_move_obj and (i + 1) < len(analysis_data) else None

        has_cpl_in_pair = False
        if white_analysis_data and white_analysis_data['cpl_for_move'] > 0:
            has_cpl_in_pair = True
        if black_analysis_data and black_analysis_data['cpl_for_move'] > 0:
            has_cpl_in_pair = True

        # Process White's move
        if white_move_obj:
            current_move_pair_text += f" {escape_latex_special_chars(board_for_display.san(white_move_obj))}"

            # Determine marked squares for White's move
            if board_for_display.is_castling(white_move_obj):
                king_from_sq = white_move_obj.from_square
                # The board's turn is WHITE before white_move_obj is pushed
                if board_for_display.is_kingside_castling(white_move_obj):
                    rook_from_sq = chess.H1
                else:  # Queenside castling
                    rook_from_sq = chess.A1
                marked_sq1 = f"{{ {chess.square_name(king_from_sq)}, {chess.square_name(rook_from_sq)} }}"
            else:
                marked_sq1 = f"{{ {chess.square_name(white_move_obj.from_square)}, {chess.square_name(white_move_obj.to_square)} }}"

            board_for_display.push(white_move_obj)  # Now board_for_display reflects state AFTER white's move
            fen1 = board_for_display.board_fen()

        # Process Black's move (if exists)
        if black_move_obj:
            current_move_pair_text += f" {escape_latex_special_chars(board_for_display.san(black_move_obj))}"

            # Determine marked squares for Black's move
            # At this point, board_for_display is in the state *after white's move* and *before black's move*.
            # Its turn is correctly BLACK.
            if board_for_display.is_castling(black_move_obj):
                king_from_sq = black_move_obj.from_square
                if board_for_display.is_kingside_castling(black_move_obj):
                    rook_from_sq = chess.H8
                else:  # Queenside castling
                    rook_from_sq = chess.A8
                marked_sq2 = f"{{ {chess.square_name(king_from_sq)}, {chess.square_name(rook_from_sq)} }}"
            else:
                marked_sq2 = f"{{ {chess.square_name(black_move_obj.from_square)}, {chess.square_name(black_move_obj.to_square)} }}"

            board_for_display.push(black_move_obj)
            fen2 = board_for_display.board_fen()
        else:
            # If no black move, the second board should show the position after white's move
            fen2 = fen1
            marked_sq2 = ""  # No black move to mark squares for

        all_calculated_move_pairs.append((
            current_move_pair_text,
            fen1, marked_sq1, white_analysis_data,
            fen2, marked_sq2, black_analysis_data,
            has_cpl_in_pair
        ))

    move_pairs_to_display = []
    if board_scope == "all":
        move_pairs_to_display = all_calculated_move_pairs
    else:  # board_scope == "smart"
        # In 'smart' mode, we only display pairs where at least one move had CPL (i.e., was not perfect)
        for pair_data in all_calculated_move_pairs:
            if pair_data[7]:  # Check has_cpl_in_pair flag
                move_pairs_to_display.append(pair_data)

    # Now, iterate through the (potentially filtered) collected move pairs and generate LaTeX
    for i, (move_text, fen1, marked_sq1, white_analysis, fen2, marked_sq2, black_analysis, _) in enumerate(
            move_pairs_to_display):
        latex_lines.append(r"\begin{minipage}{\linewidth}")
        latex_lines.append(f"\\textbf{{{move_text}}} \\\\[0.5ex]")
        latex_lines.append("\\begin{tabularx}{\\linewidth}{X X}")

        # White's move board (state AFTER White's move)
        latex_lines.append(
            f"\\chessboard[setfen={{ {fen1} }}, boardfontsize=20pt, mover=b, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, markfields={marked_sq1}] &")

        # Black's move board (state AFTER Black's move) - ONLY display if black move exists
        if marked_sq2:
            latex_lines.append(
                f"\\chessboard[setfen={{ {fen2} }}, boardfontsize=20pt, mover=w, showmover={show_mover}, linewidth=0.1em, pgfstyle=border, markfields={marked_sq2}] \\\\")
        else:
            latex_lines.append("\\\\")  # Just close the row if no black board

        latex_lines.append("\\end{tabularx}")

        # --- Add Move-by-Move Analysis below boards ---
        if white_analysis or black_analysis:  # Only add this section if there's analysis data
            latex_lines.append("\\begin{tabularx}{\\linewidth}{X X}")

            # First line: Eval scores
            white_eval_line = f"\\textit{{Eval: {get_eval_string(white_analysis['eval_after_played_move'])}}}" if white_analysis else ""
            black_eval_line = f"\\textit{{Eval: {get_eval_string(black_analysis['eval_after_played_move'])}}}" if black_analysis else ""
            latex_lines.append(f"{white_eval_line} & {black_eval_line} \\\\")

            # Second line: Best move / CPL details
            white_details_line = ""
            if white_analysis:
                if white_analysis['played_move'] != white_analysis['engine_best_move_from_pos'] and not \
                        white_analysis['engine_eval_before_played_move'].is_mate():
                    white_details_line = f"\\textit{{Best: {escape_latex_special_chars(white_analysis['engine_best_move_from_pos'].uci())}}}, \\textit{{Loss: {white_analysis['cpl_for_move']}}}cp, {classify_move_loss(white_analysis['cpl_for_move'])}"
                else:
                    white_details_line = "\\textit{Best Move}"

            black_details_line = ""
            if black_analysis:
                if black_analysis['played_move'] != black_analysis['engine_best_move_from_pos'] and not \
                        black_analysis['engine_eval_before_played_move'].is_mate():
                    black_details_line = f"\\textit{{Best: {escape_latex_special_chars(black_analysis['engine_best_move_from_pos'].uci())}}}, \\textit{{Loss: {black_analysis['cpl_for_move']}}}cp, {classify_move_loss(black_analysis['cpl_for_move'])}"
                else:
                    black_details_line = "\\textit{Best Move}"

            latex_lines.append(f"{white_details_line} & {black_details_line} \\\\")

            latex_lines.append("\\end{tabularx}")

        latex_lines.append("\\vspace{2ex}")  # Add some vertical space between board pairs
        latex_lines.append(r"\end{minipage}")
    return latex_lines


def export_game_to_latex(game, game_index, output_dir, analysis_data, notation_type, show_mover=False,
                         display_boards=False, board_scope="smart"):
    """
    Exports a single chess game, its notation, analysis summary, and optional move-by-move
    boards with analysis to a LaTeX file. This is the orchestrator method.
    """
    latex = []

    # 1. Add game metadata
    latex.extend(_generate_game_metadata_latex(game, game_index))

    # 2. Add game notation
    latex.extend(_generate_game_notation_latex(game, notation_type))

    # 3. Add game statistics section (analysis summary)
    latex.extend(_generate_analysis_summary_latex(analysis_data))

    # 4. Add move-by-move board analysis (if enabled)
    if display_boards:
        latex.extend(_generate_board_analysis_latex(game, analysis_data, show_mover, board_scope))

    game_file = output_dir / f"game_{game_index:03}.tex"
    with open(game_file, "w") as f:
        f.write("\n".join(latex))


def delete_output_directory(output_dir_path):
    """Deletes the output directory if it exists."""
    output_dir = Path(output_dir_path)
    if output_dir.exists() and output_dir.is_dir():
        print(f"Deleting existing output directory: {output_dir}")
        try:
            shutil.rmtree(output_dir)
        except OSError as e:
            print(f"Error deleting directory {output_dir}: {e}", file=sys.stderr)
            sys.exit(1)


def compile_latex_to_pdf(output_dir_path, main_tex_file="chess_book.tex"):
    """Compiles the LaTeX files to PDF and cleans up auxiliary files."""
    output_dir = Path(output_dir_path)
    main_tex_path = output_dir / main_tex_file

    if not main_tex_path.exists():
        print(f"Main LaTeX file not found: {main_tex_path}", file=sys.stderr)
        return

    print(f"Compiling LaTeX files in {output_dir}...")
    # Compile multiple times for TOC and references
    for i in range(LATEX_COMPILE_PASSES):  # Usually 2-3 runs are sufficient
        try:
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", main_tex_file],
                cwd=output_dir,
                capture_output=True,
                text=True,
                check=False  # Do not raise exception for non-zero exit code, we check it manually
            )
            if result.returncode != 0:
                print(f"LaTeX compilation failed on pass {i + 1}. Output:", file=sys.stderr)
                print(result.stdout, file=sys.stderr)
                print(result.stderr, file=sys.stderr)
                # Continue for multiple passes even if one fails, to get more errors
        except FileNotFoundError:
            print("Error: pdflatex command not found. Please ensure LaTeX is installed and in your PATH.",
                  file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred during LaTeX compilation: {e}", file=sys.stderr)
            sys.exit(1)

    print("LaTeX compilation complete. Cleaning up auxiliary files...")
    # Clean up auxiliary files
    aux_extensions = ['.aux', '.log', '.lof', '.toc', '.out', '.fls', '.fdb_latexmk', '.synctex.gz']
    for f in output_dir.iterdir():
        if f.suffix in aux_extensions or (f.is_file() and f.name.startswith("game_") and f.suffix == '.tex'):
            try:
                f.unlink()
            except OSError as e:
                print(f"Error deleting auxiliary file {f}: {e}", file=sys.stderr)


def generate_chess_book(pgn_path, output_dir_path, notation_type="figurine", display_boards=False, board_scope="smart"):
    pgn_path = Path(pgn_path)
    output_dir = Path(output_dir_path)
    output_dir.mkdir(parents=True, exist_ok=True)  # Recreate the directory after deletion if it was deleted

    with open(pgn_path) as f:
        games = []
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            games.append(game)

    tex_master = [LATEX_HEADER]

    # Initialize engine once for all games
    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        # Configure engine for multi-threading and hash table size for better performance
        engine.configure({"Threads": 2, "Hash": 128})
    except Exception as e:
        print(
            f"Error starting Stockfish engine: {e}. Please ensure '{ENGINE_PATH}' is correct and Stockfish is installed.")
        print("Analysis features (CPL, blunders, best moves) will be disabled for all games.")
        engine = None

    for idx, game in enumerate(games):
        try:
            print(f"Exporting game {idx + 1}/{len(games)} to LaTeX...")

            analysis_data = []
            if engine:
                analysis_data = analyze_game_with_stockfish(game, engine)
            else:
                print(f"Skipping Stockfish analysis for game {idx + 1} due to engine error.")

            export_game_to_latex(game, idx + 1, output_dir, analysis_data, notation_type, display_boards=display_boards,
                                 board_scope=board_scope)
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(f"⚠️ Skipping game {idx + 1} due to an error during processing: {e}")

    tex_master.append(LATEX_FOOTER)
    with open(output_dir / "chess_book.tex", "w") as f:
        f.write("\n".join(tex_master))

    if engine:
        engine.quit()  # Close engine when done with all games


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
    parser.add_argument(
        "--display_boards",
        action="store_true",
        help="Enable display of chessboards. If off (default), only notation is displayed."
    )
    parser.add_argument(
        "--board_scope",
        type=str,
        choices=["all", "smart"],
        default="smart",
        help="When --display_boards is enabled, specify whether to display boards for 'all' moves or only 'smart' moves (i.e., moves with CPL > 0, default: 'smart')."
    )

    args = parser.parse_args()

    # 1. Parse command line args (already done by argparse)

    # 2. Delete the output directory if it exists
    delete_output_directory(args.output_dir)

    # 3. Run generate_chess_book
    generate_chess_book(args.pgn_file, args.output_dir, args.notation_type, display_boards=args.display_boards,
                        board_scope=args.board_scope)

    # 4. Compile the latex files with pdflatex
    compile_latex_to_pdf(args.output_dir)