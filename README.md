# 🎮 CivilwarHelper (LoL & VALORANT In-house Discord Bot)

**CivilwarHelper** is a free-to-use Discord bot designed to help League of Legends and VALORANT communities organize friendly 5v5 custom matches (in-houses). It provides interactive recruitment lobbies, role/position selection, and balanced team distribution based on official Riot rank tiers.

---

## 📺 Video Demonstration (For Riot Games API Review)
Since reviewers do not join Discord servers during the review process, please watch our public demonstration video below showing the full user flow and UI interactions:

👉 **[Watch Demo Video on YouTube](https://youtu.be/td8K6VnwtHg)**

---

## 🛠️ Commands Demonstrated in the Video

* **`/register` — Account Registration (RSO / OAuth to be implemented)**
  * Links a user's Discord account with their Riot ID for custom game participation.
  * *Note: Upon VALORANT Production API Key approval, this command will be updated within 30 days to use Riot Sign-On (RSO) OAuth so players can securely authenticate and opt-in.*
* **`/unregister` — Account Unlink & Data Removal (Opt-out)**
  * Unlinks the registered Riot account and removes the user's profile data from the bot. Allows users to fix input errors or opt-out of data sharing at any time.
* **`/create-inhouse` — Friendly 5v5 Custom Match Lobby**
  * Creates an interactive recruitment lobby to gather 10 players, select preferred roles/positions, and start a balanced 5v5 custom match with friends.
* **`/lolprofile` — League of Legends Profile Summary**
  * Displays registered users' League of Legends profiles, including official rank tiers, preferred positions, and in-house participation history.
* **`/valprofile` — VALORANT Profile Summary**
  * Displays registered users' VALORANT profiles, including official rank tiers, preferred agent roles, and in-house participation history.

---

## 🔒 Riot Games API Policy & RSO Compliance
* **Free & Community-Focused**: 100% free to use with no commercial charge or locked features.
* **No Alternative MMR/ELO**: We do not create custom skill rating systems or leaderboards. Official rank tiers are strictly referenced to balance teams for friendly 5v5 custom lobbies.
* **Player Privacy (RSO)**: We will integrate Riot Sign-On (OAuth) prior to displaying VALORANT player stats in production, ensuring explicit player opt-in.

---
*CivilwarHelper isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties.*

롤 / 발로란트 내전 모집, 팀 밸런싱, 전적 기록용 디스코드 봇. (Python 3.10+)

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt   # 테스트까지 돌릴 거면 pip install -e ".[dev]"
copy .env.example .env          # 토큰이랑 API 키 입력
python bot.py
```

- `TEST_GUILD_IDS`에 서버 ID 넣어두면 해당 서버에 바로 슬래시 커맨드 동기화됨 (비워두면 글로벌 동기화라 좀 걸림)
- DB는 `data/civilwarhelper.db`에 자동 생성됨

## 환경변수

- `DISCORD_TOKEN`: 봇 토큰
- `RIOT_API_KEY`: 롤 솔랭/자랭 티어 및 주포지션 조회용
- `RIOT_VAL_API_KEY`: 발로란트 경쟁전 티어/주역할군 조회용 (없어도 봇은 돌아감. 티어만 안 불러와지는데 `/userprofile`에서 체감티어 넣으면 됨)
- 발로 주역할군은 최근 10판 모스트 기준 (40% 미만이면 Flex). 신캐 나오면 `config/positions.py`의 `VAL_AGENT_ROLES`에 추가.

## 체크 / 테스트

```bash
python scripts/check.py
python -m pytest -q
```

## 폴더 구조

- `src/civilwarhelper/app.py` - 봇 클라이언트, 이벤트, 실행
- `src/civilwarhelper/config/` - 환경변수, 티어 점수표, 포지션/요원 매핑
- `src/civilwarhelper/db/` - sqlite 쿼리 모음
- `src/civilwarhelper/riot/` - 라이엇 API (롤/발로)
- `src/civilwarhelper/services/` - 밸런싱, 팀 이름 추천, 전적 계산
- `src/civilwarhelper/ui/` - 메시지 포맷팅, 버튼/셀렉트 뷰, 이모지 캐시
- `src/civilwarhelper/commands/` - 슬래시 명령어 등록
