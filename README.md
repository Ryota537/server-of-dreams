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
- Unknown where to find max autoPlayTimes, dailyLessonTimes, or musicCourseFreeChallengeTimes (we default to all 0 for now).
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