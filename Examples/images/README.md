# Images
These are optional images that can be displayed as the tabs on the TV dashboard.

<img src="Examples/images/screenshot.png" width="700" alt="HassJellyBoard View Icons">

They are referenced in the sample yaml files as `icon: steve:media-icon-tvshowskids`

See:

```
Examples/Lovelace/lovelace_config_tvshowkids.yaml
```

# Included Icons
 - media-icon-tvshows
 - media-icon-tvshowskids
 - media-icon-movies
 - media-icon-movieskids
 - media-icon-movieschristmas

# Installing Custom Icons

1. Place `steves-custom-icons.js` at:

```
config/www/community/steves-custom-icons/steves-custom-icons.js
```

2. In Home Assistant> Dashboards> Resources

3. Add as a JS resource: `/hacsfiles/steves-custom-icons/steves-custom-icons.js`

**You do not need the SVG files in this folder. They are embedded in the js file and only included here for illustration.**


