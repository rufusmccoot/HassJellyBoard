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

# --- LOAD CONFIG ---
yaml_ruamel = YAML()
with open(os.path.join(os.path.dirname(__file__), 'config.yaml'), 'r', encoding='utf-8') as f:
    config = yaml_ruamel.load(f)

JELLYFIN_URL = config.get('jellyfin_url')
JELLYFIN_API_KEY = config.get('jellyfin_token')
OUTPUT_DIR = config.get('output_dir', r'\\172.16.0.4\config\views\jellyboard')

from datetime import datetime

CYAN = "\033[36m"
RESET = "\033[0m"

def log_cyan(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{CYAN}[{now}] {msg}{RESET}")

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

# --- FETCH TV SHOWS ---
def get_user_id():
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    url_users = f"{JELLYFIN_URL}/Users"
    resp = requests.get(url_users, headers=headers, verify=False)
    if resp.status_code == 200:
        users = resp.json()
        if not users:
            raise Exception("[Jellyboard] No users found in Jellyfin.")
        if len(users) > 1:
            log_cyan(f"Multiple users found in Jellyfin. Using the first user: {users[0]['Name']}")
        else:
            log_cyan(f"Using Jellyfin user: {users[0]['Name']}")
        return users[0]["Id"]
    else:
        raise Exception(f"[Jellyboard] Failed to get user ID from /Users. Response: {resp.text}")

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

from flask import Flask, request, jsonify
import threading
import random

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    log_cyan('Webhook received:', data)
    # If webhook Type or ItemType is 'Movie', refresh YAML for all movie libraries
    if data.get('Type') == 'Movie' or data.get('ItemType') == 'Movie':
        log_cyan('Webhook Type or ItemType is Movie. Triggering YAML rebuild for all movie libraries (5-Movies, 3-Movies Kids, 4-Movies Christmas).')
        for lib in libraries:
            if item_type_map.get(lib['name']) == 'Movie':
                log_cyan(f'Triggering YAML rebuild for library: {lib["name"]}')
                threading.Thread(target=rebuild_yaml, args=(lib['name'],)).start()
        return '', 204

    # If ItemType is Series, Season, or Episode, refresh YAML and cache for all tv libraries
    if data.get('ItemType') in ('Series', 'Season', 'Episode'):
        log_cyan('Webhook ItemType is Series/Season/Episode. Debounced: Triggering YAML and cache rebuild for all TV libraries (Series) only if not rebuilt recently.')
        import time
        global last_rebuild_time
        try:
            last_rebuild_time
        except NameError:
            last_rebuild_time = {}
        DEBOUNCE_SECONDS = 30
        now = time.time()
        for lib in libraries:
            if item_type_map.get(lib['name']) == 'Series':
                last = last_rebuild_time.get(lib['name'], 0)
                if now - last > DEBOUNCE_SECONDS:
                    last_rebuild_time[lib['name']] = now
                    log_cyan(f'Triggering YAML rebuild for library: {lib["name"]}')
                    threading.Thread(target=rebuild_yaml, args=(lib['name'],)).start()
                    log_cyan(f'Triggering cache rebuild for library: {lib["name"]}')
                    threading.Thread(target=rebuild_cache, args=(lib['name'],)).start()
                else:
                    log_cyan(f"Skipping redundant rebuild for {lib["name"]} (debounced)")
        return '', 204

    # Try to find the library name from ancestors if present
    library_name = None
    ancestors = data.get('Ancestors', [])
    if ancestors:
        for ancestor in ancestors:
            if ancestor.get('Type') == 'Folder':
                library_name = ancestor.get('Name')
                break
    # If not found, try to fetch item details from Jellyfin
    if not library_name and 'ItemId' in data:
        item_id = data['ItemId']
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        url = f"{JELLYFIN_URL}/Items/{item_id}"
        try:
            resp = requests.get(url, headers=headers, verify=False)
            resp.raise_for_status()
            item = resp.json()
            # Try to get the library name from the response
            if 'Library' in item and 'Name' in item['Library']:
                library_name = item['Library']['Name']
            elif 'ParentId' in item:
                # Optionally, walk up to the root parent if needed (not implemented here)
                log_cyan(f"Could not directly determine library for item {item_id}, ParentId: {item['ParentId']}")
        except Exception as e:
            log_cyan(f"Error fetching item details for library lookup: {e}")
    if not library_name:
        log_cyan('Could not determine library from webhook, skipping YAML rebuild.')
        return '', 204
    log_cyan(f'Triggering YAML rebuild for library: {library_name}')
    threading.Thread(target=rebuild_yaml, args=(library_name,)).start()
    # Also trigger cache rebuild for 2-TV or 1-TV Kids
    if library_name in ("2-TV", "1-TV Kids"):
        log_cyan(f'It is a TV library so we are also triggering cache rebuild for library: {library_name}')
        threading.Thread(target=rebuild_cache, args=(library_name,)).start()
    return '', 204

@app.route('/rebuild_yaml/<library>', methods=['POST', 'GET'])
def rebuild_yaml_endpoint(library):
    log_cyan(f'YAML rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_yaml, args=(library,)).start()
    return jsonify({'status': 'rebuilding', 'library': library})

@app.route('/rebuild_yaml/all', methods=['POST', 'GET'])
def rebuild_yaml_all():
    log_cyan('YAML rebuild triggered for all libraries')
    threading.Thread(target=rebuild_yaml, args=('all',)).start()
    return jsonify({'status': 'rebuilding', 'library': 'all'})


@app.route('/rebuild_cache/<library>', methods=['POST', 'GET'])
def rebuild_cache_endpoint(library):
    log_cyan(f'Cache rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_cache, args=(library,)).start()
    return jsonify({'status': 'rebuilding_cache', 'library': library})


# In-memory state for randomizer
RANDOMIZER_STATE = {}

@app.route('/play_random_episode', methods=['POST'])
def play_random_episode():
    data = request.get_json(force=True)
    series_id = data.get('series_id')
    if not series_id:
        return jsonify({'error': 'Missing series_id'}), 400
    log_cyan(f'Requesting random episode for series {series_id}')
    # Step 1: Pick a random episode
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    user_id = get_user_id()
    url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
    params = {
        "ParentId": series_id,
        "IncludeItemTypes": "Episode",
        "Recursive": "true"
    }
    log_cyan(f"Fetching episodes for series {series_id}")
    try:
        resp = requests.get(url, headers=headers, params=params, verify=False)
        log_cyan(f"  Jellyfin response: {resp.status_code}")
        resp.raise_for_status()
        episodes = resp.json().get('Items', [])
        if not episodes:
            log_cyan(f"  No episodes found for series {series_id}")
            return jsonify({'error': 'No episodes found'}), 404
        episode = random.choice(episodes)
        episode_id = episode.get('Id')
        log_cyan(f"Selected random episode {episode_id} from series {series_id}")
    except Exception as e:
        log_cyan(f"Error fetching episodes for series {series_id}: {e}")
        return jsonify({'error': str(e)}), 500
    # Step 2: Trigger Jellyfin to play the episode on Android TV client
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    try:
        # Fetch all active sessions
        sessions_url = f"{JELLYFIN_URL}/Sessions"
        log_cyan(f"Fetching sessions from: {sessions_url}")
        sessions_resp = requests.get(sessions_url, headers=headers, verify=False)
        sessions_resp.raise_for_status()
        sessions = sessions_resp.json()
        android_tv_session = next((s for s in sessions if s.get("Client") == "Android TV"), None)
        if not android_tv_session:
            log_cyan("No active Android TV session found.")
            return jsonify({'error': 'No active Android TV session found'}), 404
        session_id = android_tv_session.get("Id")
        log_cyan(f"Using Android TV session id: {session_id}")
        # Save randomizer state in memory
        RANDOMIZER_STATE = {
            "session_id": session_id,
            "series_id": series_id,
            "last_episode_id": episode_id
        }
        # Display toast alerting user to what we are playing
        show_name = get_show_name_by_series_id(series_id)
        if show_name:
            toast_data = {
                "header": f"Playing random episode of",
                "text": show_name
            }
            toast_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Message"
            toast_resp = requests.post(toast_url, headers=headers, json=toast_data, verify=False)
            toast_resp.raise_for_status()
            log_cyan(f"Toast sent: '{toast_data['header']}: {toast_data['text']}'")
        # Send play command as query parameters
        play_url = f"{JELLYFIN_URL}/Sessions/{session_id}/Playing"
        play_params = {
            "playCommand": "PlayNow",
            "ItemIds": episode_id
        }
        log_cyan(f"Sending play command as query params: {play_params} to {play_url}")
        play_resp = requests.post(play_url, headers=headers, params=play_params, verify=False)
        log_cyan(f"  Jellyfin response: {play_resp.status_code}")
        if play_resp.ok:
            return jsonify({'status': 'playing', 'episode_id': episode_id, 'session_id': session_id})
        else:
            log_cyan(f"Play command error: {play_resp.text[:200]}")
            return jsonify({'error': 'Failed to trigger playback on Jellyfin', 'details': play_resp.text}), 500
    except Exception as e:
        log_cyan(f"Error triggering Jellyfin playback: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/jf_webhook', methods=['POST'])
def jf_webhook():
    data = request.json
    log_cyan("Received webhook")
    event = data.get("Event")
    session = data.get("Session", {})
    client = session.get("Client")
    session_id = session.get("Id")
    item_id = data.get("ItemId")
    item = data.get("Item", {})
    position = data.get("PositionTicks", 0)
    duration = item.get("RunTimeTicks", 0)
    log_cyan(f"Event: {event}")
    log_cyan(f"Client: {client}")
    log_cyan(f"SessionId: {session_id}")
    log_cyan(f"ItemId: {item_id}")
    log_cyan(f"Position: {position}")
    log_cyan(f"Duration: {duration}")
    global RANDOMIZER_STATE
    # Only act if playback stopped on Android TV and it finished naturally, and state matches
    if event == "PlaybackStopped" and client == "Android TV":
        log_cyan("Since client is Android TV, checking to see if we were randomizing")
        if (RANDOMIZER_STATE.get("session_id") == session_id and
            RANDOMIZER_STATE.get("last_episode_id") == item_id and
            duration and position and (duration - position) < 30 * 10**7):  # 30 seconds in ticks
            log_cyan("The session_id and last_episode_id match our last randomize call. Queue next random episode.")
            # Call play_random_episode logic for the same series
            from flask import current_app
            with current_app.test_request_context(json={"series_id": RANDOMIZER_STATE["series_id"]}):
                play_random_episode()
        else:
            log_cyan("The media that just finished playing is not one we requested. Taking no action.")
            RANDOMIZER_STATE = {}
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
            log_cyan(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
            lib["library_id"] = None
    # Remove libraries with no ID
    to_remove = [lib for lib in libraries if not lib["library_id"]]
    for lib in to_remove:
        libraries.remove(lib)

def rebuild_yaml(library):
    log_cyan(f'Rebuilding YAML for library: {library}')
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
            log_cyan(f"Generated {filename} in {local_yaml_dir}")
            try:
                dest_path = os.path.join(OUTPUT_DIR, filename)
                shutil.copyfile(local_path, dest_path)
                log_cyan(f"Copied {filename} to {dest_path}")
            except Exception as e:
                log_cyan(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")

        if library == 'all':
            for lib in libraries:
                process_lib(lib)
            log_cyan("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied! 😘")
        else:
            norm = normalize_name(library)
            match = next((lib for lib in libraries if normalize_name(lib["name"]) == norm), None)
            if not match:
                log_cyan(f"  No config found for library '{library}'. Skipping YAML rebuild.")
                return
            process_lib(match)
    except Exception as e:
        log_cyan(f"  Error rebuilding YAML for {library}: {e}")

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
        log_cyan(f"Could not fetch series {series_id}: {resp.status_code} {resp.text}")
        return None
    try:
        items = resp.json().get("Items", [])
        if items and "Name" in items[0]:
            return items[0]["Name"]
        else:
            log_cyan(f"No series found for ID {series_id}. Response: {resp.text}")
            return None
    except Exception as e:
        log_cyan(f"Error decoding JSON for series {series_id}: {e}")
        return None

def normalize_name(name):
    return name.lower().replace(' ', '').replace('_', '').replace('-', '')

def get_cache_path(library):
    safe_name = library.lower().replace(" ", "_")
    return os.path.join(os.getcwd(), f'episode_cache_{safe_name}.json')

def save_cache(library, cache):
    path = get_cache_path(library)
    with open(path, 'w') as f:
        json.dump(cache, f)
    log_cyan(f"Saved cache for {library} to {path}")

def load_cache(library):
    path = get_cache_path(library)
    if not os.path.exists(path):
        log_cyan(f"No cache file found for {library} at {path}, returning empty cache.")
        return {}
    with open(path, 'r') as f:
        cache = json.load(f)
    log_cyan(f"Loaded cache for {library} from {path}")
    return cache

def rebuild_cache(library):
    log_cyan(f"Rebuilding episode cache for library: {library}")
    try:
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
            log_cyan(f"Unsupported library for cache: {library}")
            return
        # Find the library ID from your libraries config
        user_id = get_user_id()
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        url = f"{JELLYFIN_URL}/Users/{user_id}/Views"
        resp = requests.get(url, headers=headers, verify=False)
        resp.raise_for_status()
        views = resp.json().get("Items", [])
        lib_id = None
        for view in views:
            if normalize_name(view["Name"]) == normalize_name(jellyfin_lib_name):
                lib_id = view["Id"]
                break
        if not lib_id:
            log_cyan(f"Could not find Jellyfin library ID for {library}")
            return
        # Fetch all series in this library
        url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
        params = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Fields": "PrimaryImageAspectRatio,Genres",
            "ParentId": lib_id
        }
        resp = requests.get(url, headers=headers, params=params, verify=False)
        resp.raise_for_status()
        series_list = resp.json().get("Items", [])
        cache = {}
        for s in series_list:
            series_id = s["Id"]
            # Fetch all episodes for this series
            ep_url = f"{JELLYFIN_URL}/Shows/{series_id}/Episodes"
            ep_params = {"UserId": user_id, "Fields": "Id"}
            ep_resp = requests.get(ep_url, headers=headers, params=ep_params, verify=False)
            if ep_resp.status_code != 200:
                log_cyan(f"Failed to fetch episodes for series {series_id}")
                continue
            episodes = ep_resp.json().get("Items", [])
            episode_ids = [ep["Id"] for ep in episodes]
            cache[series_id] = episode_ids
            log_cyan(f"Series {series_id}: {len(episode_ids)} episodes cached.")
        save_cache(library, cache)
        log_cyan(f"Cache build complete for {library}. {len(cache)} series processed.")
    except Exception as e:
        log_cyan(f"Error rebuilding cache for {library}: {e}")

if __name__ == "__main__":
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
            log_cyan(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
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
        log_cyan(f"Generated {filename} in {local_yaml_dir}")
        # Copy to HA config share
        try:
            dest_path = os.path.join(OUTPUT_DIR, filename)
            shutil.copyfile(local_path, dest_path)
            log_cyan(f"Copied {filename} to {dest_path}")
        except Exception as e:
            log_cyan(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")
    log_cyan("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied!")
