# Server of Dreams (夢のサーバー)
A certain EOSed mobile theatre idol rhythm game's WIP private server implementation.

## Run

Fill out config

Needs a postgresql database

```bash
pip install -r requirements.txt
python -m scripts.database_setup
python -m scripts.download_masterdata
python -m scripts.download_all_assets   # https://github.com/Ryota537/asset-of-dreams
python main.py
```

## Changelog
[Changelog](CHANGELOG.md)

## Features
✅ Done · 🚧 WIP · ❌ No

| Feature | | Feature | |
|---|:--:|---|:--:|
| Registration, tutorial & account import | ✅ | Character upgrades (level/awaken/sense/talent) | ✅ |
| Master data & asset serving | ✅ | Star-rank rewards | ✅ |
| Friends & inbox | ✅ | Accessory upgrades | ✅ |
| Gacha (pickup + reroll) | ✅ | Actor side stories | ✅ |
| Live play & scoring | ✅ | Episodes & read rewards | ✅ |
| Live drops (date-windowed) | ✅ | Missions & character missions | ✅ |
| Olivier SP Rate | ✅ | Anthology & auditions | ✅ |
| Stella / Olivier unlocks | ✅ | Comics & theater/MV records | ✅ |
| Song & chart purchases | ✅ | Customization & profile | ✅ |
| Shops & market | ✅ | Photos & albums | ✅ |
| Lessons & music courses | ✅ | Service-end date extension | ✅ |
| Player-rank XP & stamina | ✅ | Daily limit resets | ✅ |
| **Multiplayer (co-op, circles, Theater League)** | **🚧** | Poster (levels/breaks/stories) | ❌ |
| Login bonuses | ❌ | Live events & rankings | ❌ |
| Mission Pass | ❌ | Roulette | ❌ |
| Flash sale | ❌ | Triple-cast parties | ❌ |
| Banners | ❌ | Friend-invitation missions | ❌ |
| Player rating history | ❌ | External payments | ❌ |

## Priority Todo
- Player rating history log
- Player rank calculations (live end)
- Senses voice ids (live start)
- Episodes (verify unlocked)
- Missions

## Backburner (less important)
- GET https://lb-api.wds-stellarium.com/api/Circles/Invited -> []
- POST https://lb-api.wds-stellarium.com/api/Home/CheckReceiveLoginBonus
- POST https://lb-api.wds-stellarium.com/api/FriendInvitation/Update (friend invitation mission)

## Help Requested
Please open an issue if you know how!
- Unknown where to find login bonuses or banners (not in master data?)

A lot of game resources may be in downloaded asset bundles? Confirmation would help us a lot :)

## Will Not Implement
POST https://lb-api.wds-stellarium.com/api/Home/CheckEexternalPayment -> no electronic external payments

# Credits
All contributors on this repository, plus...

- [t-wy](https://github.com/t-wy) for user ID hashing
- [wds-sirius/Adv-Resource](https://github.com/wds-sirius/Adv-Resource) for episode data and archive (`_data/episodes/`)
- [assets-of-dreams](https://github.com/Ryota537/asset-of-dreams) for archived game assets
- [Alehero](https://github.com/Alehero/yumesute-preservation-server) for their work on some features
- [ulong32](https://github.com/Alehero/yumesute-preservation-server/issues/1) for figuring out the Olivier SpRate math