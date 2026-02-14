import requests
from ruamel.yaml import YAML
from io import StringIO
import os
import warnings
from urllib3.exceptions import InsecureRequestWarning
import shutil
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.scalarstring import FoldedScalarString
# Suppress only the single InsecureRequestWarning from urllib3 needed for self-signed/unverified certs
warnings.filterwarnings("ignore", category=InsecureRequestWarning)
import threading
from flask import Flask, request, jsonify
import random
import time
from ruamel.yaml import YAML

# --- LOAD CONFIG ---
yaml_ruamel = YAML()
with open(os.path.join(os.path.dirname(__file__), 'config.yaml'), 'r', encoding='utf-8') as f:
    config = yaml_ruamel.load(f)

JELLYFIN_URL = config.get('jellyfin_url')
JELLYFIN_API_KEY = config.get('jellyfin_token')
OUTPUT_DIR = config.get('output_dir', r'\\172.16.0.4\config\views\jellyboard')
LOG_LEVEL = config.get('log_level', 1)

from datetime import datetime

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN_CHECKMARK = "\033[32m✅\033[0m"
RED_X = "\033[31m❌\033[0m"
VERBOSE_COLOR_SCHEME = "\033[30;43m"
RESET = "\033[0m"
#Just a big ass underline
delimiter = "__________________________________________________________________________________________"

def log_cyan(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_msg = msg
    if "Started" in new_msg:
        new_msg = new_msg.replace("Started", f"{GREEN}\u25BA{CYAN} Started{CYAN}")
    if "Stopped" in new_msg:
        new_msg = new_msg.replace("Stopped", f"{RED}\u25A0{CYAN} Stopped{CYAN}")
    print(f"{CYAN}[{now}] {new_msg}{RESET}")

def log_green(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{GREEN}[{now}] {msg}{RESET}")

def log_yellow(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{YELLOW}[{now}] {msg}{RESET}")

def log_red(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{RED}[{now}] {msg}{RESET}")

def log_verbose_msg(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{VERBOSE_COLOR_SCHEME}[{now}] {msg}{RESET}")

def wait_for_tv_session_id(timeout_s=12, interval_s=0.5):
    log_yellow(f"Waiting up to {timeout_s}s for TV session...")
    deadline = time.time() + timeout_s
    last_log = 0

    while time.time() < deadline:
        sid = discover_session_id()  # your DeviceId/DeviceName matcher
        if sid:
            log_green(f"TV session found: {sid}")
            return sid

        # don’t spam logs every 0.5s
        if time.time() - last_log >= 2:
            log_yellow("...still waiting for TV session")
            last_log = time.time()

        time.sleep(interval_s)
    log_red(f"Timed out after {timeout_s}s waiting for TV session")
    return None


def discover_session_id():
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    resp = requests.get(f"{JELLYFIN_URL}/Sessions", headers=headers, verify=False)
    resp.raise_for_status()
    sessions = resp.json()

    target_device_id = (config.get("android_tv_device_id") or "").strip()
    if target_device_id:
        log_yellow(f"Attempt session discovery by DeviceId: {target_device_id}")
        s = next((x for x in sessions if x.get("DeviceId") == target_device_id), None)
        if s:
            log_green(f"SessionId discovered via DeviceId: {s['Id']}")
            return s["Id"]
    # fallback
    log_yellow(f"Session not found by DeviceId, attempting discovery via DeviceName \"living room tv\"")
    s = next((x for x in sessions if (x.get("DeviceName") or "").strip().lower() == "living room tv"), None)
    if not s:
        log_red("No active Living Room TV session found.")
        return None
    log_green(f"SessionId discovered via DeviceName: {s['Id']}")
    return s["Id"]

# Make libraries and item_type_map available globally
libraries = [
    {
        "name": "2-TV",
        "path": "tvshows",
        "script_service": "script.jellyfin_play_tv_based_libraries",
        "icon": "steve:media-icon-tvshows"
    },
    {
        "name": "1-TV Kids",
        "path": "tvshowskids",
        "script_service": "script.jellyfin_play_tv_based_libraries",
        "icon": "steve:media-icon-tvshowskids"
    },
    {
        "name": "5-Movies",
        "path": "movies",
        "script_service": "script.jellyfin_play_movie_based_libraries",
        "icon": "steve:media-icon-movies"
    },
    {
        "name": "3-Movies Kids",
        "path": "movieskids",
        "script_service": "script.jellyfin_play_movie_based_libraries",
        "icon": "steve:media-icon-movieskids"
    },
    {
        "name": "4-Movies Christmas",
        "path": "movieschristmas",
        "script_service": "script.jellyfin_play_movie_based_libraries",
        "icon": "steve:media-icon-movieschristmas"
    },
    {
        "name": "Music",
        "path": "music",
        "script_service": "script.jellyfin_play_content_from_music",
        "icon": "mdi:music"
    }
]
item_type_map = {
    "2-TV": "Series",
    "1-TV Kids": "Series",
    "5-Movies": "Movie",
    "3-Movies Kids": "Movie",
    "4-Movies Christmas": "Movie",
    "Music": "Audio",
    "Random": "Series"
}

def send_toast(toast_url, headers, toast_data):
    try:
        toast_resp = requests.post(toast_url, headers=headers, json=toast_data, verify=False)
        toast_resp.raise_for_status()
        if LOG_LEVEL > 1:
            log_verbose_msg(f"Toast sent: '{toast_data['header']}: {toast_data['text']}'")
    except Exception as e:
        log_red(f"Toast failed: {e}")

# --- FETCH TV SHOWS ---
def get_user_id():
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    url_users = f"{JELLYFIN_URL}/Users"
    resp = requests.get(url_users, headers=headers, verify=False)
    if resp.status_code == 200:
        users = resp.json()
        if not users:
            raise Exception("No users found in Jellyfin.")
        if len(users) > 1:
            log_cyan(f"Multiple users found in Jellyfin. Using the first user: {users[0]['Name']}")
        else:
            log_cyan(f"Using Jellyfin user: {users[0]['Name']}")
        return users[0]["Id"]
    else:
        raise Exception(f"Failed to get user ID from /Users. Response: {resp.text}")

def get_tv_shows():
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    user_id = get_user_id()
    url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
    params = {
        "IncludeItemTypes": "Series",
        "Recursive": "true",
        "Fields": "PrimaryImageAspectRatio,Genres"
    }
    resp = requests.get(url, headers=headers, params=params, verify=False)
    resp.raise_for_status()
    return resp.json()

# --- GENERATE YAML (SKELETON) ---
def generate_lovelace_yaml(tv_shows, library_title="2-TV Shows", library_path="tvshows", script_service="script.jellyfin_play_content_from_tvshows", icon=None, jellyfin_views=None):
    """
    Generate a Home Assistant Lovelace view YAML for a given Jellyfin TV show library.
    """
    if jellyfin_views is None:
        jellyfin_views = []
    # Build button-card YAML for each show, sorted alphabetically
    items = tv_shows.get('Items', [])
    # Sort using 'SortName' if present, else fallback to 'Name'
    items_sorted = sorted(
        items,
        key=lambda s: (s.get('SortName') or s.get('Name') or '').lower()
    )
    cards = []
    # Build a map of library ID to CollectionType from jellyfin_views
    library_type_map = {}
    for lib in jellyfin_views:
        if lib.get('Id') and lib.get('CollectionType'):
            library_type_map[lib['Id']] = lib['CollectionType']

    for show in items_sorted:
        show_name = show.get('Name')
        show_id = show.get('Id')
        # Try to get CollectionType from the item
        collection_type = show.get('CollectionType')
        # If missing, try to get from parent library
        if not collection_type and show.get('ParentId'):
            collection_type = library_type_map.get(show['ParentId'])
        # Fallback: guess from script_service or library_title
        if not collection_type:
            if 'movie' in (script_service or '').lower():
                collection_type = 'movies'
            elif 'music' in (script_service or '').lower():
                collection_type = 'music'
            else:
                collection_type = 'tvshows'
        # Use Jellyfin's direct image URL
        entity_picture = f"{JELLYFIN_URL}/Items/{show_id}/Images/Primary?api_key={JELLYFIN_API_KEY}"
        card = {
            "type": "custom:button-card",
            "variables": {"this_media": DoubleQuotedScalarString(show_name), "media_id": show_id, "media_type": collection_type},
            "name": '[[[ return variables.this_media; ]]]',
            "confirmation": {
                "text": FoldedScalarString('[[[ return "Do you want to play \\x22" + variables.this_media + "\\x22?"; ]]]')
            },
            "aspect_ratio": "1/1.5",
            "size": 150,
            "styles": None,
            "card": [
                {"height": "100px"},  
                {"--mdc-ripple-color": "blue"},
                {"--mdc-ripple-press-opacity": "0.5"}
            ],
            "entity_picture": entity_picture,
            "show_entity_picture": True,
            "show_name": True,
            "show_icon": False,
            # For movie libraries, call the movie script and pass media_content_id
            "tap_action": (
                {
                    "action": "call-service",
                    "service": script_service,
                    "service_data": {
                        "media_content_id": '[[[ return variables.media_id; ]]]'
                    }
                } if script_service == "script.jellyfin_play_movie_based_libraries" else {
                    "action": "call-service",
                    "service": script_service,
                    "service_data": {
                        "media_id": '[[[ return variables.media_id; ]]]',
                        "media_type": '[[[ return variables.media_type; ]]]'
                    }
                }
            )
        }
        cards.append(card)

    # Compose the full view
    # Compose the grid card for media buttons
    # Insert remote card as the first grid card, then all media button-cards
    remote_card = {
        "show_name": True,
        "show_icon": True,
        "type": "button",
        "icon": "mdi:remote-tv",
        "name": "TV Remote",
        "tap_action": {
            "action": "navigate",
            "navigation_path": "/dashboard-media/remote"
        }
    }
    grid_cards = [remote_card] + cards
    grid_card = {
        "type": "grid",
        "square": True,
        "columns": 5,
        "cards": grid_cards
    }
    stack_cards = [
        {
            "type": "custom:button-card",
            "color_type": "label-card",
            "template": "section-header",
            "name": library_title
        },
        grid_card
    ]

    view = {
        "title": library_title,
        "path": library_path,
        "type": "sidebar",
        "icon": icon,
        "cards": [
            {
                "type": "vertical-stack",
                "cards": stack_cards
            }
        ]
    }
    # Use ruamel.yaml for correct Home Assistant/Lovelace indentation
    yaml_ruamel = YAML()
    yaml_ruamel.preserve_quotes = True  # Preserve quotes on scalars
    yaml_ruamel.default_flow_style = False
    yaml_ruamel.indent(mapping=2, sequence=4, offset=2)
    stream = StringIO()
    yaml_ruamel.dump(view, stream)
    return stream.getvalue()

def print_jellyfin_libraries():
    """Fetch and print all library (folder) names and IDs from Jellyfin."""
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    url = f"{JELLYFIN_URL}/Library/SelectableMediaFolders"
    try:
        resp = requests.get(url, headers=headers, verify=False)
        resp.raise_for_status()
        data = resp.json()
        log_cyan("Jellyfin Libraries (Name -> Id):")
        for lib in data.get("Items", []):
            log_cyan(f"   {lib['Name']}: {lib['Id']}")
    except Exception as e:
        log_cyan(f"Error fetching Jellyfin libraries: {e}")
        log_cyan(f"Response content: {getattr(resp, 'text', 'No response')}")



app = Flask(__name__)

@app.route('/rebuild_yaml/<library>', methods=['POST', 'GET'])
def rebuild_yaml_endpoint(library):
    log_yellow(f'YAML rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_yaml, args=(library,)).start()
    return jsonify({'status': 'rebuilding', 'library': library})

@app.route('/rebuild_yaml/all', methods=['POST', 'GET'])
def rebuild_yaml_all():
    log_yellow('YAML rebuild triggered for all libraries')
    threading.Thread(target=rebuild_yaml, args=('all',)).start()
    return jsonify({'status': 'rebuilding', 'library': 'all'})

@app.route('/rebuild_cache/<library>', methods=['POST', 'GET'])
def rebuild_cache_endpoint(library):
    log_yellow(f'Cache rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_cache, args=(library,)).start()
    return jsonify({'status': 'rebuilding_cache', 'library': library})

# In-memory state for randomizer
RANDOMIZER_STATE = {}

@app.route('/play_movie', methods=['POST'])
def play_movie():
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    yaml_ruamel = YAML()
    # Defensive: extract item_id from JSON or query param
    if LOG_LEVEL > 1:
        log_verbose_msg(f"play_movie request: args={dict(request.args)}, json={request.get_json(silent=True)}")
    item_id = request.args.get('item_id')
    if not item_id:
        data = request.get_json(silent=True) or {}
        item_id = data.get('item_id')
    if not item_id:
        log_red("Missing item_id in both query params and JSON body")
        log_red(f"Request.args: {dict(request.args)}")
        log_red(f"Request.get_json(silent=True): {request.get_json(silent=True)}")
        return jsonify({'error': 'Missing item_id'}), 400
    # Load config each time to get updated session id
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = yaml_ruamel.load(f)
    session_id = config_data.get('android_tv_session_id', 'ab2f036321e914934450c05ea24fc36b')
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    # Get movie name from Jellyfin
    movie_name = None
    try:
        url = f"{JELLYFIN_URL}/Items"
        params = {"ids": item_id, "api_key": JELLYFIN_API_KEY}
        resp = requests.get(url, params=params, verify=False)
        if resp.status_code == 200:
            items = resp.json().get("Items", [])
            if items and "Name" in items[0]:
                movie_name = items[0]["Name"]
            else:
                movie_name = "Unknown Movie"
        else:
            log_red(f"Could not fetch movie {item_id}: {resp.status_code} {resp.text}")
            movie_name = "Unknown Movie"
    except Exception as e:
        log_red(f"Error fetching movie name for {item_id}: {e}")
        movie_name = "Unknown Movie"
    # Toast (parallel)
    toast_data = {
        "header": f"Playing movie",
        "text": movie_name
    }
    toast_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Message"
    try:
        threading.Thread(target=send_toast, args=(toast_url, headers, toast_data), daemon=True).start()
    except Exception as e:
        log_red(f"Toast failed: {e}")
    # Play command
    play_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Playing"
    play_params = {
        "playCommand": "PlayNow",
        "ItemIds": item_id
    }
    if LOG_LEVEL > 1:
        log_verbose_msg(f"Sending play command as query params: {play_params} to {play_url}")
    play_resp = requests.post(play_url, headers=headers, params=play_params, verify=False)
    if LOG_LEVEL > 1:
        log_verbose_msg(f"Jellyfin response: {play_resp.status_code}")
    if play_resp.ok:
        log_verbose_msg(f"{delimiter}")
        log_green(f"Played movie '{movie_name}' | Item: {item_id} | Jellyfin 200 OK.")
        return jsonify({'status': 'playing', 'item_id': item_id, 'session_id': session_id})
    else:
        log_red(f"Failed to play movie '{movie_name}' | Item: {item_id} | Jellyfin error: {play_resp.text}")
        return jsonify({'error': 'Failed to trigger movie playback on Jellyfin', 'details': play_resp.text}), 500

@app.route('/play_random_episode', methods=['POST'])
def play_random_episode():
    # --- CONFIG ---
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    yaml_ruamel = YAML()
    # Defensive: extract series_id from JSON or query param
    if LOG_LEVEL > 1:
        log_verbose_msg(f"play_random_episode request: args={dict(request.args)}, json={request.get_json(silent=True)}")
    series_id = request.args.get('series_id')
    if not series_id:
        data = request.get_json(silent=True) or {}
        series_id = data.get('series_id')
    if not series_id:
        log_red("Missing series_id in both query params and JSON body")
        return jsonify({'error': 'Missing series_id'}), 400
    # Load config each time to get updated session id
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = yaml_ruamel.load(f)
    global config
    config = config_data

    # Find which cache file contains the requested series_id
    cache_dir = os.getcwd()
    cache_files = [f for f in os.listdir(cache_dir) if f.startswith('episode_cache_') and f.endswith('.yaml')]
    cache = None
    cache_file_used = None
    for fname in cache_files:
        path = os.path.join(cache_dir, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                file_cache = yaml_ruamel.load(f) or []
            if any(s for s in file_cache if s['series_id'] == series_id):
                cache = file_cache
                cache_file_used = fname
                break
        except Exception as e:
            log_red(f"Failed to read cache file {fname}: {e}")
    if not cache:
        log_red(f"Series {series_id} not found in any episode_cache_*.yaml file.")
        return jsonify({'error': 'Series not found in cache'}), 404
    series_entry = next((s for s in cache if s['series_id'] == series_id), None)
    if not series_entry:
        log_red(f"Series {series_id} not found in cache file {cache_file_used}.")
        return jsonify({'error': 'Series not found in cache'}), 404
    episode_ids = series_entry.get('episode_ids', [])
    if not episode_ids:
        log_red(f"No episodes cached for series {series_id} (cache file: {cache_file_used}).")
        return jsonify({'error': 'No episodes found in cache'}), 404
    show_name = series_entry.get('series_name', 'Unknown')
    episode_id = random.choice(episode_ids)

    # At this point, cache, series_entry, episode_ids, show_name, episode_id are all set from the correct cache file
    # Step 2: Use discover session id
    session_id = wait_for_tv_session_id(timeout_s=12, interval_s=0.5)
    if not session_id:
        return jsonify({'error': 'TV Jellyfin session not active yet'}), 503

    headers = {"X-Emby-Token": JELLYFIN_API_KEY}

    # Display toast alerting user to what we are playing
    toast_data = {
        "header": f"Playing random episode of",
        "text": show_name
    }
    toast_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Message"
    try:
        threading.Thread(target=send_toast, args=(toast_url, headers, toast_data), daemon=True).start()
    except Exception as e:
        log_red(f"Toast failed: {e}")
    # Save randomizer state in memory
    global RANDOMIZER_STATE
    RANDOMIZER_STATE = {
        "session_id": session_id,
        "series_id": series_id
    }
    if LOG_LEVEL > 1:
        log_verbose_msg(f"RANDOMIZER_STATE: {RANDOMIZER_STATE}")

    # Send play command as query parameters
    log_yellow(f"Play attempt 1 using session {session_id}")
    play_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Playing"
    play_params = {
        "playCommand": "PlayNow",
        "ItemIds": episode_id
    }
    if LOG_LEVEL > 1:
        log_verbose_msg(f"Sending play command as query params: {play_params} to {play_url}")
    play_resp = requests.post(play_url, headers=headers, params=play_params, verify=False)
    if LOG_LEVEL > 1:
        log_verbose_msg(f"Jellyfin response code: {play_resp.status_code}")
        log_verbose_msg(f"Jellyfin response headers: {dict(play_resp.headers)}")
        log_verbose_msg(f"Jellyfin response text: {play_resp.text}")
    if play_resp.ok:
        log_green(f"Played '{show_name}' | Series: {series_id} | Episode: {episode_id} | Jellyfin 200 OK.")
        return jsonify({'status': 'playing', 'episode_id': episode_id, 'session_id': session_id})
    log_red(f"Play attempt 1 failed: {play_resp.status_code} {play_resp.text[:200]}")
    session_id2 = wait_for_tv_session_id(timeout_s=6, interval_s=0.5)
    if not session_id2:
        return jsonify({'error': 'TV session not available'}), 503
    RANDOMIZER_STATE["session_id"] = session_id2
    log_yellow(f"Play attempt 2 using session {session_id2}")
    play_url = f"{JELLYFIN_URL}/Sessions/{session_id2}/Playing"
    play_resp2 = requests.post(play_url, headers=headers, params=play_params, verify=False)
    if play_resp2.ok:
        return jsonify({'status': 'playing', 'episode_id': episode_id, 'session_id': session_id2})
    log_red(f"Play attempt 2 failed: {play_resp2.status_code} {play_resp2.text[:200]}")
    return jsonify({'error': 'Failed to trigger playback on Jellyfin', 'details': play_resp2.text}), 500

@app.route('/jf_webhook', methods=['POST'])
def jf_webhook():
    if LOG_LEVEL > 1:
        log_verbose_msg(f"Webhook received from {request.remote_addr} with Content-Type: {request.content_type}")
    try:
        data = request.get_json(force=True)
    except Exception as e:
        log_red(f"Failed to parse JF webhookJSON: {e}")
        data = None
    if not data:
        try:
            raw = request.data.decode('utf-8', errors='replace')
            if LOG_LEVEL > 1:
                log_verbose_msg(f"Raw webhook body: {raw}")
        except Exception as e:
            log_red(f"Could not decode raw body: {e}")
        return jsonify({"error": "Unsupported content type or invalid JSON"}), 415
    # Build concise cyan log for key fields
    notification_type = data.get("NotificationType") or data.get("Event")
    series_name = data.get("SeriesName") or (data.get("Item", {}) or {}).get("SeriesName")
    series_id = data.get("SeriesId") or (data.get("Item", {}) or {}).get("SeriesId")
    season_num = data.get("SeasonNumber00") or (data.get("Item", {}) or {}).get("SeasonNumber00")
    episode_num = data.get("EpisodeNumber00") or (data.get("Item", {}) or {}).get("EpisodeNumber00")
    episode_name = data.get("Name") or (data.get("Item", {}) or {}).get("Name")
    item_id = data.get("ItemId") or data.get("MediaSourceId") or data.get("Id")
    session_id = data.get("Id") or (data.get("Session", {}) or {}).get("Id")
    client = (data.get("Client") or data.get("ClientName") or data.get("DeviceName") or (data.get("Session", {}) or {}).get("Client"))
    if notification_type == 'PlaybackStart':
        event_short_name = 'Started'
    elif notification_type == 'PlaybackStop':
        event_short_name = 'Stopped'
    else:
        event_short_name = notification_type
    log_cyan(f"{delimiter}")
    if series_id:
        log_cyan(f"{event_short_name} [{series_name} - S{season_num}E{episode_num}] on {client}")
        log_cyan(f"{event_short_name} [Series ID: {series_id} | Episode ID: {item_id}]")
    else:
        log_cyan(f"{event_short_name} movie on {client}")
        log_cyan(f"{event_short_name} [Movie ID: {item_id}]")
    # Support both Emby-style and flat Jellyfin notification formats
    # Event type
    event = data.get("Event") or data.get("NotificationType")
    # Client info
    client = None
    if "Session" in data and isinstance(data["Session"], dict):
        client = data["Session"].get("Client")
    if not client:
        client = data.get("Client") or data.get("ClientName") or data.get("DeviceName")
    # Session ID
    session_id = None
    if "Session" in data and isinstance(data["Session"], dict):
        session_id = data["Session"].get("Id")
    if not session_id:
        session_id = data.get("Id") or data.get("SessionId")
    # Item ID
    item_id = data.get("ItemId") or data.get("MediaSourceId") or data.get("Id")
    # Item info
    item = data.get("Item", {})
    # Position/Duration
    position = data.get("PositionTicks", 0) or data.get("PlaybackPositionTicks", 0)
    duration = item.get("RunTimeTicks", 0) or data.get("RunTimeTicks", 0)
    global RANDOMIZER_STATE
    # Only act if playback stopped on Android TV and it finished naturally, and state matches
    if (event in ["PlaybackStopped", "PlaybackStop"]) and (client == "Android TV"):
        if LOG_LEVEL > 1:
            log_verbose_msg("Webhook reported client is Android TV, checking to see if we were randomizing")
        # Ticks: some webhooks use PlaybackPositionTicks, others PositionTicks
        # Use series_id from webhook (flat or nested)
        webhook_series_id = data.get("SeriesId") or (data.get("Item", {}) or {}).get("SeriesId")
        if LOG_LEVEL > 1:
            log_verbose_msg(f"RANDOMIZER_STATE: {RANDOMIZER_STATE}")
            log_verbose_msg(f"WEBHOOK INFO: session_id: {session_id} | series_id: {webhook_series_id}")
        if (RANDOMIZER_STATE.get("session_id") == session_id and
            RANDOMIZER_STATE.get("series_id") == webhook_series_id and
            duration and position and (duration - position) < 30 * 10**7):  # 30 seconds in ticks
            log_cyan(f"{GREEN_CHECKMARK}{CYAN} SessionId + SeriesId match our fingerprint. Ended with < 30s. Queue next random episode.")
            # Call play_random_episode logic for the same series
            from flask import current_app
            with current_app.test_request_context(json={"series_id": RANDOMIZER_STATE["series_id"]}):
                play_random_episode()
        else:
            time_remaining = (duration - position) / 10_000_000
            if (duration and position and (duration - position) < 30 * 10**7): # 30 seconds in ticks
                log_cyan(f"{RED_X}{CYAN} SessionId + SeriesId do not match our fingerprint, even though it ended with < 30s. Taking no action.")
            else:
                log_cyan(f"{RED_X}{CYAN} SessionId + SeriesId do not match our fingerprint, and it ended with {time_remaining}s. Taking no action.")
            if LOG_LEVEL > 1:
                log_verbose_msg(f"RANDOMIZER_STATE: {RANDOMIZER_STATE}")
                log_verbose_msg(f"webhook_series_id: {webhook_series_id}")
                log_verbose_msg(f"session_id: {session_id}")
                log_verbose_msg(f"duration: {duration}")
                log_verbose_msg(f"position: {position}")
                log_verbose_msg(f"time_remaining: {time_remaining}")
            #RANDOMIZER_STATE = {}
    return jsonify({"status": "ok"})


def update_library_ids():
    """Fetch library IDs from Jellyfin and update the global libraries list."""
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    user_id = get_user_id()
    url = f"{JELLYFIN_URL}/Users/{user_id}/Views"
    resp = requests.get(url, headers=headers, verify=False)
    resp.raise_for_status()
    jellyfin_views = resp.json().get("Items", [])
    for lib in libraries:
        norm_name = normalize_name(lib["name"])
        match = next((view for view in jellyfin_views if normalize_name(view["Name"]) == norm_name), None)
        if match:
            lib["library_id"] = match["Id"]
        else:
            log_yellow(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
            lib["library_id"] = None
    # Remove libraries with no ID
    to_remove = [lib for lib in libraries if not lib["library_id"]]
    for lib in to_remove:
        libraries.remove(lib)

def rebuild_yaml(library):
    log_yellow(f"{delimiter}")
    log_yellow(f'Rebuilding YAML for library: {library}')
    try:
        update_library_ids()
        user_id = get_user_id()
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        local_yaml_dir = os.path.join(os.getcwd(), 'GeneratedLovelaceYamls')
        os.makedirs(local_yaml_dir, exist_ok=True)

        global libraries, item_type_map
        def process_lib(lib):
            item_type = item_type_map.get(lib["name"], "Series")
            url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
            params = {
                "IncludeItemTypes": item_type,
                "Recursive": "true",
                "Fields": "PrimaryImageAspectRatio,Genres",
                "ParentId": lib["library_id"]
            }
            resp = requests.get(url, headers=headers, params=params, verify=False)
            resp.raise_for_status()
            items = resp.json()
            # Fetch jellyfin_views for this user
            views_url = f"{JELLYFIN_URL}/Users/{user_id}/Views"
            views_resp = requests.get(views_url, headers=headers, verify=False)
            views_resp.raise_for_status()
            jellyfin_views = views_resp.json().get("Items", [])
            yaml_str = generate_lovelace_yaml(
                items,
                library_title=lib["name"],
                library_path=lib["path"],
                script_service=lib["script_service"],
                icon=lib.get("icon"),
                jellyfin_views=jellyfin_views
            )
            filename = f"lovelace_config_{lib['path']}.yaml"
            local_path = os.path.join(local_yaml_dir, filename)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(yaml_str)
            log_yellow(f"Generated {filename} in {local_yaml_dir}")
            try:
                dest_path = os.path.join(OUTPUT_DIR, filename)
                shutil.copyfile(local_path, dest_path)
                log_yellow(f"Copied {filename} to {dest_path}")
            except Exception as e:
                log_red(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")

        if library == 'all':
            for lib in libraries:
                process_lib(lib)
            log_yellow("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied!")
        else:
            norm = normalize_name(library)
            match = next((lib for lib in libraries if normalize_name(lib["name"]) == norm), None)
            if not match:
                log_yellow(f"  No config found for library '{library}'. Skipping YAML rebuild.")
                return
            process_lib(match)
    except Exception as e:
        log_yellow(f"  Error rebuilding YAML for {library}: {e}")

from ruamel.yaml import YAML
import json

def get_show_name_by_series_id(series_id):
    """Given a series ID, return the show (series) name from Jellyfin."""
    url = f"{JELLYFIN_URL}/Items"
    params = {
        "ids": series_id,
        "api_key": JELLYFIN_API_KEY
    }
    resp = requests.get(url, params=params, verify=False)
    if resp.status_code != 200:
        log_red(f"Could not fetch series {series_id}: {resp.status_code} {resp.text}")
        return None
    try:
        items = resp.json().get("Items", [])
        if items and "Name" in items[0]:
            return items[0]["Name"]
        else:
            log_red(f"No series found for ID {series_id}. Response: {resp.text}")
            return None
    except Exception as e:
        log_red(f"Error decoding JSON for series {series_id}: {e}")
        return None

def normalize_name(name):
    return name.lower().replace(' ', '').replace('_', '').replace('-', '')

def get_cache_path(library):
    safe_name = library.lower().replace(" ", "_")
    return os.path.join(os.getcwd(), f'episode_cache_{safe_name}.yaml')

def save_cache(library, cache):
    path = get_cache_path(library)
    yaml_ruamel = YAML()
    yaml_ruamel.default_flow_style = False
    with open(path, 'w', encoding='utf-8') as f:
        yaml_ruamel.dump(cache, f)
    log_yellow(f"Saved cache for {library} to {path}")

def load_cache(library):
    path = get_cache_path(library)
    if not os.path.exists(path):
        log_red(f"No cache file found for {library} at {path}, returning empty cache.")
        return []
    yaml_ruamel = YAML()
    with open(path, 'r', encoding='utf-8') as f:
        cache = yaml_ruamel.load(f)
    log_yellow(f"Loaded cache for {library} from {path}")
    return cache or []

def rebuild_cache(library):
    log_yellow(f"{delimiter}")
    log_yellow(f"Rebuilding episode cache for library: {library}")
    try:
        # Auto-discover correct Jellyfin user_id
        user_id = get_user_id()
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        # Map library name to Jellyfin item types
        item_type_map = {
            "2-TV": "Series",
            "1-TV Kids": "Series"
        }
        # Use the normalized name to match the library
        normalized_library = normalize_name(library)
        if normalized_library in ["tvshows", "tv","2tv"]:
            jellyfin_lib_name = "2-TV"
        elif normalized_library in ["tvkids","1tvkids"]:
            jellyfin_lib_name = "1-TV Kids"
        else:
            log_red(f"Unsupported library for cache: {library}")
            return
        # Dynamically fetch library_id from Jellyfin
        views_url = f"{JELLYFIN_URL}/Users/{user_id}/Views"
        views_resp = requests.get(views_url, headers=headers, verify=False)
        if views_resp.status_code != 200:
            log_red(f"Failed to fetch library views for user {user_id}: {views_resp.status_code} {views_resp.text}")
            return
        views = views_resp.json().get("Items", [])
        lib_id = None
        for view in views:
            if normalize_name(view["Name"]) == normalize_name(jellyfin_lib_name):
                lib_id = view["Id"]
                break
        if not lib_id:
            log_red(f"Could not find Jellyfin library ID for {library} (looked for {jellyfin_lib_name})")
            return
        # Fetch all series in this library
        url_series = f"{JELLYFIN_URL}/Users/{user_id}/Items"
        params_series = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "ParentId": lib_id
        }
        resp_series = requests.get(url_series, headers=headers, params=params_series, verify=False)
        resp_series.raise_for_status()
        series_list = resp_series.json().get("Items", [])
        # Fetch all episodes in one call
        url_episodes = f"{JELLYFIN_URL}/Users/{user_id}/Items"
        params_episodes = {
            "IncludeItemTypes": "Episode",
            "Recursive": "true",
            "ParentId": lib_id
        }
        resp_episodes = requests.get(url_episodes, headers=headers, params=params_episodes, verify=False)
        resp_episodes.raise_for_status()
        episodes_list = resp_episodes.json().get("Items", [])
        # Group episodes by SeriesId
        from collections import defaultdict
        episodes_by_series = defaultdict(list)
        for ep in episodes_list:
            series_id = ep.get('SeriesId')
            if series_id:
                episodes_by_series[series_id].append(ep['Id'])
        cache = []
        for series in series_list:
            series_id = series["Id"]
            series_name = series.get("Name", "Unknown")
            episode_ids = episodes_by_series.get(series_id, [])
            cache.append({
                "series_id": series_id,
                "series_name": series_name,
                "episode_ids": episode_ids
            })
            log_yellow(f"Series {series_id} ({series_name}): {len(episode_ids)} episodes cached.")
        save_cache(library, cache)
        log_yellow(f"Cache build complete for {library}. {len(cache)} series processed.")
    except Exception as e:
        log_red(f"Error rebuilding cache for {library}: {e}")

if __name__ == "__main__":
    if LOG_LEVEL > 1:
        log_verbose_msg("Starting Jellyboard in verbose mode...")
    else:
        log_yellow("Starting Jellyboard...")
    app.run(host='0.0.0.0', port=8064)
    resp = requests.get(url, params=params, verify=False)
    resp.raise_for_status()
    jellyfin_views = resp.json().get("Items", [])

    # Map library names to IDs using user views
    for lib in libraries:
        norm_name = normalize_name(lib["name"])
        match = next((view for view in jellyfin_views if normalize_name(view["Name"]) == norm_name), None)
        if match:
            lib["library_id"] = match["Id"]
        else:
            log_red(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
            lib["library_id"] = None

    # Remove libraries with no ID
    libraries = [lib for lib in libraries if lib["library_id"]]

    # Map library name to Jellyfin item types (customize as needed)
    item_type_map = {
        "2-TV": "Series",
        "1-TV Kids": "Series",
        "5-Movies": "Movie",
        "3-Movies Kids": "Movie",
        "4-Movies Christmas": "Movie",
        "Music": "Audio",
        "Random": "Series"
    }

    user_id = get_user_id()
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}

    # Create the local folder for generated YAMLs
    local_yaml_dir = os.path.join(os.getcwd(), 'GeneratedLovelaceYamls')
    os.makedirs(local_yaml_dir, exist_ok=True)

    for lib in libraries:
        item_type = item_type_map.get(lib["name"], "Series")
        url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
        params = {
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Fields": "PrimaryImageAspectRatio,Genres",
            "ParentId": lib["library_id"]
        }
        resp = requests.get(url, headers=headers, params=params, verify=False)
        resp.raise_for_status()
        items = resp.json()
        yaml_str = generate_lovelace_yaml(
            items,
            library_title=lib["name"],
            library_path=lib["path"],
            script_service=lib["script_service"],
            icon=lib.get("icon")
        )
        filename = f"lovelace_config_{lib['path']}.yaml"
        local_path = os.path.join(local_yaml_dir, filename)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        log_yellow(f"Generated {filename} in {local_yaml_dir}")
        # Copy to HA config share
        try:
            dest_path = os.path.join(OUTPUT_DIR, filename)
            shutil.copyfile(local_path, dest_path)
            log_yellow(f"Copied {filename} to {dest_path}")
        except Exception as e:
            log_red(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")
    log_yellow("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied!")
