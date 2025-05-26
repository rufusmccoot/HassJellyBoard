import requests
import yaml
import os
import warnings
from urllib3.exceptions import InsecureRequestWarning
import shutil
# Suppress only the single InsecureRequestWarning from urllib3 needed for self-signed/unverified certs
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

# --- LOAD CONFIG ---
with open(os.path.join(os.path.dirname(__file__), 'config.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

JELLYFIN_URL = config.get('jellyfin_url')
JELLYFIN_API_KEY = config.get('jellyfin_token')
OUTPUT_DIR = config.get('output_dir', r'\\172.16.0.4\config\views\jellyboard')

# Make libraries and item_type_map available globally
libraries = [
    {
        "name": "TV Shows",
        "path": "tvshows",
        "script_service": "script.jellyfin_play_content_from_tvshows",
        "icon": "steve:media-icon-tvshows"
    },
    {
        "name": "TV Kids",
        "path": "tvshowskids",
        "script_service": "script.jellyfin_play_content_from_tv_kids",
        "icon": "steve:media-icon-tvshowskids"
    },
    {
        "name": "Movies",
        "path": "movies",
        "script_service": "script.jellyfin_play_content_from_movies",
        "icon": "steve:media-icon-movies"
    },
    {
        "name": "Movies Kids",
        "path": "movieskids",
        "script_service": "script.jellyfin_play_content_from_movies_kids",
        "icon": "steve:media-icon-movieskids"
    },
    {
        "name": "Christmas Movies",
        "path": "movieschristmas",
        "script_service": "script.jellyfin_play_content_from_movies_christmas",
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
    "TV Shows": "Series",
    "TV Kids": "Series",
    "Movies": "Movie",
    "Movies Kids": "Movie",
    "Christmas Movies": "Movie",
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
            raise Exception("No users found in Jellyfin.")
        if len(users) > 1:
            print(f"Multiple users found in Jellyfin. Using the first user: {users[0]['Name']}")
        else:
            print(f"Using Jellyfin user: {users[0]['Name']}")
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
def generate_lovelace_yaml(tv_shows, library_title="TV Shows", library_path="tvshows", script_service="script.jellyfin_play_content_from_tvshows", icon=None, jellyfin_views=None):
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
            "variables": {"this_media": show_name, "media_id": show_id, "media_type": collection_type},
            "name": '[[[ return variables.this_media; ]]]',
            "confirmation": {
                "text": '[[[ return "Do you want to play \"" + variables.this_media + "\"?"; ]]]'
            },
            "aspect_ratio": "1/1.5",
            "size": 150,
            "styles": None,
            "card": [
                "height: 100px",
                "--mdc-ripple-color: blue",
                "--mdc-ripple-press-opacity: 0.5"
            ],
            "entity_picture": entity_picture,
            "show_entity_picture": True,
            "show_name": True,
            "show_icon": False,
            "tap_action": {
                "action": "call-service",
                "service": script_service,
                "service_data": {
                    "media_id": '[[[ return variables.media_id; ]]]',
                    "media_type": '[[[ return variables.media_type; ]]]'
                }
            }
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
    # Use yaml.dump with indent=2 and default_flow_style=False for correct formatting
    return yaml.dump(view, sort_keys=False, default_flow_style=False, indent=2)

def print_jellyfin_libraries():
    """Fetch and print all library (folder) names and IDs from Jellyfin."""
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    url = f"{JELLYFIN_URL}/Library/SelectableMediaFolders"
    try:
        resp = requests.get(url, headers=headers, verify=False)
        resp.raise_for_status()
        data = resp.json()
        print("Jellyfin Libraries (Name -> Id):")
        for lib in data.get("Items", []):
            print(f"{lib['Name']}: {lib['Id']}")
    except Exception as e:
        print(f"Error fetching Jellyfin libraries: {e}")
        print(f"Response content: {getattr(resp, 'text', 'No response')}")

from flask import Flask, request, jsonify
import threading
import random

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print('Webhook received:', data)
    # If webhook Type or ItemType is 'Movie', refresh YAML for all movie libraries
    if data.get('Type') == 'Movie' or data.get('ItemType') == 'Movie':
        print('Webhook Type or ItemType is Movie. Triggering YAML rebuild for all movie libraries (Movies, Movies Kids, Christmas Movies).')
        for lib in libraries:
            if item_type_map.get(lib['name']) == 'Movie':
                print(f'Triggering YAML rebuild for library: {lib["name"]}')
                threading.Thread(target=rebuild_yaml, args=(lib['name'],)).start()
        return '', 204

    # If ItemType is Series, Season, or Episode, refresh YAML and cache for all tv libraries
    if data.get('ItemType') in ('Series', 'Season', 'Episode'):
        print('Webhook ItemType is Series/Season/Episode. Debounced: Triggering YAML and cache rebuild for all TV libraries (Series) only if not rebuilt recently.')
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
                    print(f'Triggering YAML rebuild for library: {lib["name"]}')
                    threading.Thread(target=rebuild_yaml, args=(lib['name'],)).start()
                    print(f'Triggering cache rebuild for library: {lib["name"]}')
                    threading.Thread(target=rebuild_cache, args=(lib['name'],)).start()
                else:
                    print(f"Skipping redundant rebuild for {lib['name']} (debounced)")
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
                print(f"Could not directly determine library for item {item_id}, ParentId: {item['ParentId']}")
        except Exception as e:
            print(f"Error fetching item details for library lookup: {e}")
    if not library_name:
        print('Could not determine library from webhook, skipping YAML rebuild.')
        return '', 204
    print(f'Triggering YAML rebuild for library: {library_name}')
    threading.Thread(target=rebuild_yaml, args=(library_name,)).start()
    # Also trigger cache rebuild for TV Shows or TV Kids
    if library_name in ("TV Shows", "TV Kids"):
        print(f'It is a TV library so we are also triggering cache rebuild for library: {library_name}')
        threading.Thread(target=rebuild_cache, args=(library_name,)).start()
    return '', 204

@app.route('/rebuild_yaml/<library>', methods=['POST', 'GET'])
def rebuild_yaml_endpoint(library):
    print(f'Manual YAML rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_yaml, args=(library,)).start()
    return jsonify({'status': 'rebuilding', 'library': library})

@app.route('/rebuild_yaml/all', methods=['POST', 'GET'])
def rebuild_yaml_all():
    print('Manual YAML rebuild triggered for all libraries')
    threading.Thread(target=rebuild_yaml, args=('all',)).start()
    return jsonify({'status': 'rebuilding', 'library': 'all'})


@app.route('/rebuild_cache/<library>', methods=['POST', 'GET'])
def rebuild_cache_endpoint(library):
    print(f'Manual cache rebuild triggered for library: {library}')
    threading.Thread(target=rebuild_cache, args=(library,)).start()
    return jsonify({'status': 'rebuilding_cache', 'library': library})

@app.route('/random_episode', methods=['GET'])
def random_episode():
    series_id = request.args.get('series_id')
    print(f'Request for random episode from series {series_id}')
    return jsonify({'episode_id': 'placeholder-episode-id'})

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
            print(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
            lib["library_id"] = None
    # Remove libraries with no ID
    to_remove = [lib for lib in libraries if not lib["library_id"]]
    for lib in to_remove:
        libraries.remove(lib)

def rebuild_yaml(library):
    print(f'Rebuilding YAML for library: {library}')
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
            print(f"Generated {filename} in {local_yaml_dir}")
            try:
                dest_path = os.path.join(OUTPUT_DIR, filename)
                shutil.copyfile(local_path, dest_path)
                print(f"Copied {filename} to {dest_path}")
            except Exception as e:
                print(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")

        if library == 'all':
            for lib in libraries:
                process_lib(lib)
            print("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied! 😘")
        else:
            norm = normalize_name(library)
            match = next((lib for lib in libraries if normalize_name(lib["name"]) == norm), None)
            if not match:
                print(f"No config found for library '{library}'. Skipping YAML rebuild.")
                return
            process_lib(match)
    except Exception as e:
        print(f"Error rebuilding YAML for {library}: {e}")

import json

def normalize_name(name):
    return name.lower().replace(' ', '').replace('_', '')

def get_cache_path(library):
    safe_name = library.lower().replace(" ", "_")
    return os.path.join(os.getcwd(), f'episode_cache_{safe_name}.json')

def save_cache(library, cache):
    path = get_cache_path(library)
    with open(path, 'w') as f:
        json.dump(cache, f)
    print(f"Saved cache for {library} to {path}")

def load_cache(library):
    path = get_cache_path(library)
    if not os.path.exists(path):
        print(f"No cache file found for {library} at {path}, returning empty cache.")
        return {}
    with open(path, 'r') as f:
        cache = json.load(f)
    print(f"Loaded cache for {library} from {path}")
    return cache

def rebuild_cache(library):
    print(f'Rebuilding episode cache for library: {library}')
    try:
        # Map library name to Jellyfin item types
        item_type_map = {
            "TV Shows": "Series",
            "TV Kids": "Series"
        }
        # Use the normalized name to match the library
        normalized_library = normalize_name(library)
        if normalized_library in ["tvshows", "tv"]:
            jellyfin_lib_name = "TV Shows"
        elif normalized_library in ["tvkids"]:
            jellyfin_lib_name = "TV Kids"
        else:
            print(f"Unsupported library for cache: {library}")
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
            print(f"Could not find Jellyfin library ID for {library}")
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
                print(f"Failed to fetch episodes for series {series_id}")
                continue
            episodes = ep_resp.json().get("Items", [])
            episode_ids = [ep["Id"] for ep in episodes]
            cache[series_id] = episode_ids
            print(f"Series {series_id}: {len(episode_ids)} episodes cached.")
        save_cache(library, cache)
        print(f"Cache build complete for {library}. {len(cache)} series processed.")
    except Exception as e:
        print(f"Error rebuilding cache for {library}: {e}")

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
            print(f"WARNING: Could not find Jellyfin library for '{lib['name']}'. Please check spelling.")
            lib["library_id"] = None

    # Remove libraries with no ID
    libraries = [lib for lib in libraries if lib["library_id"]]

    # Map library name to Jellyfin item types (customize as needed)
    item_type_map = {
        "TV Shows": "Series",
        "TV Shows-Kids": "Series",
        "Movies": "Movie",
        "Movies-Kids": "Movie",
        "Movies Christmas": "Movie",
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
        print(f"Generated {filename} in {local_yaml_dir}")
        # Copy to HA config share
        try:
            dest_path = os.path.join(OUTPUT_DIR, filename)
            shutil.copyfile(local_path, dest_path)
            print(f"Copied {filename} to {dest_path}")
        except Exception as e:
            print(f"Failed to copy {filename} to {OUTPUT_DIR}: {e}")
    print("All library YAMLs generated in 'GeneratedLovelaceYamls' and copied! 😘")
