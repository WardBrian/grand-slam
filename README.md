# grand-slam

A plugin for [mlb-led-scoreboard](https://github.com/WardBrian/mlb-led-scoreboard).

## Example config


`config.json`:

```json
{
  "rotation": {
    "screens": [
      { "kind": "grand_slam", "seconds": 60, "with_priority": 0 }
    ]
  },
  "plugins": {
    "grand_slam": {
      "tournament_ids": [
        "189-2026"
      ],
      "include_doubles": false
    }
  }
}
```

`189-2026` is the 2026 US Open


`colors/scoreboard.json`:
```json
{
  "plugins" : {
    "grand_slam": {
      "background": {
        "r": 0,
        "g": 40,
        "b": 140
      },
      "tournament": {
        "r": 255,
        "g": 212,
        "b": 1
      },
      "player": {
        "r": 255,
        "g": 255,
        "b": 255
      },
      "serving": {
        "r": 255,
        "g": 212,
        "b": 1
      },
      "winner": {
        "r": 121,
        "g": 172,
        "b": 118
      },
      "dropped_set": {
        "r": 150,
        "g": 150,
        "b": 150
      },
      "status": {
        "r": 255,
        "g": 255,
        "b": 255
      }
    }
  }
}
```

`coordinates/w64h32.json`:

```json
{
  "plugins": {
    "grand_slam": {
      "tournament": {
        "x": 0,
        "y": 7,
        "width": 64,
        "font_name": "5x8"
      },
      "p1": {
        "x": 1,
        "y": 16
      },
      "p2": {
        "x": 1,
        "y": 23
      },
      "status": {
        "x": 0,
        "y": 31,
        "width": 64
      }
    }
  }
}
```
