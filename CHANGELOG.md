# Pre-EOS
2026/07/17 - EOS announced (RIP)

2026/07/17 - Development begins

2026/07/18 - Masterdata/assets routes implemented

2026/07/18 - Account registration and tutorial implemented

2026/07/18 - Basic friends system implemented

2026/07/18 - Game hints and splash read statuses implemented

2026/07/19 - Inbox receive/bulk receive implemented

2026/07/19 - Live start and stamina

2026/07/19 - Live end, drops, ratings, clear lamps

2026/07/19 - Episodes (and read rewards)

2026/07/20 - Party Edits (no triple cast)

2026/07/20 - Gacha Pulls (exclude non pickup gachas and reroll gachas)

2026/07/20 - Music Shop + Market

2026/07/20 - Character Level Up, Awakening, Sense Enhance, Talent Bloom

2026/09/28 - EOS 🫡 (some server side math just got very very hard or impossible...)

# Post-EOS
2026/09/30 - Fix swapped actor vocal/concentration base stats (Status Key 0/2 mislabel); corrected masterdata + download script + Status/LiveStatus key maps

2026/09/30 - Add account takeovers, fix character level up math

2026/09/30 - Masterdata + asset downloads now pull from the asset-of-dreams release

2026/09/30 - Profile editing implemented

2026/09/30 - Set costume, actor portal character, home display preference, home BGM

2026/09/30 - Favorite costumes and favorite stamps

2026/09/30 - Accessory level up

2026/09/30 - Music video / theater story watch records now persist

2026/09/30 - Fix: AuditionClear no longer serializes the account userId into its Key(4) game field; byte[] fields serialize as msgpack bin

2026/09/30 - Add constants.yml for hardcoded/generous server constants

2026/09/30 - Mission subsystem: progress tracking + reward claims (Missions/receiveRewards, receiveCurrentRewards)

2026/09/30 - Character missions: star-point rewards (receiveAllMission/Bulk) and key-mission rewards

2026/09/30 - Actor side-story unlock (ReleaseSideStory)

2026/09/30 - Sense enhance and talent bloom now drive character-mission/mission progress

2026/09/30 - Fix: AddExperience rounds EXP per item before multiplying quantity (matches official captures) + applies experience bonus

2026/09/30 - Fix: story Read/ReadAll gate on episode release and advance character reading progress; GetDetails fills local metadata

2026/09/30 - Fix: ExchangeMusic gates on unlock condition (store/story) and story-episode reads

2026/09/30 - Add game_state helper (per-account transactional state + mission progress) shared by gameplay routes

2026/09/30 - Customization now validates ownership and drives missions (favorite stamp 21, profile intro 28 / trophy 27)

2026/09/30 - Photo generation, album arranging (simple/detail), tags, main page, and local photo image serving

2026/09/30 - Lessons: party edit + lesson lives with score rewards and star points

2026/09/30 - Music course lives: entry fees/free attempts, stage grading, certification rewards

2026/09/30 - Player-rank XP + stamina restore and daily usage accounting at live finish

2026/09/30 - Anthology/audition and concert progression + rewards on live finish

2026/09/30 - Daily limits now reset usage counters (autoplay/lesson/course) at 05:00 JST