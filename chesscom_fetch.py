import requests
import os

HEADERS = {
    "User-Agent": "MyChessApp/1.0 (contact: your_email@example.com)"
}

def get_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch archives: {r.status_code}")
    return r.json()["archives"]

def download_pgn_from_archive(archive_url):
    url = archive_url + "/pgn"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        raise Exception(f"Failed to download PGN: {r.status_code}")
    return r.text

def get_player_stats(username):
    url = f"https://api.chess.com/pub/player/{username}/stats"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return {}
    return r.json()

def save_combined_pgn(username, output_file):
    archives = get_archives(username)
    print(f"Found {len(archives)} archives.")

    all_pgn = ""
    for archive in archives:
        print(f"Downloading archive: {archive}")
        try:
            pgn = download_pgn_from_archive(archive)
            all_pgn += pgn + "\n\n"
        except Exception as e:
            print(f"Warning: {e}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(all_pgn)
    print(f"✅ Combined PGN saved to {output_file}")

def print_player_summary(username):
    stats = get_player_stats(username)
    if not stats:
        print("No stats available.")
        return

    print(f"\n📊 Stats for {username}:")
    for category in ['chess_blitz', 'chess_rapid', 'chess_bullet']:
        if category in stats:
            print(f"  {category}:")
            print(f"    Rating: {stats[category]['last']['rating']}")
            print(f"    Games: {stats[category]['record']}")
        else:
            print(f"  {category}: No data")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download Chess.com games for a user.")
    parser.add_argument("username", help="Chess.com username")
    parser.add_argument("-o", "--output", default="games.pgn", help="Output PGN file")
    parser.add_argument("--stats", action="store_true", help="Print player stats")

    args = parser.parse_args()

    save_combined_pgn(args.username, args.output)

    if args.stats:
        print_player_summary(args.username)
