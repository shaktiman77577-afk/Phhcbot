# Haryana Court Clerk 2026 — Score Report Bot

Registration before 4 PM, marks submission after, live shift-difficulty and
cutoff-band reporting, admin panel, branded PDF export.

Built for Advt. No. 36C/SSSC/HR/2026. Paper pattern: GK 50 + English 20 = 70,
0.25 negative marking. 8 exam dates × 3 shifts = 24 slots.

---

## Setup

**1. Railway Volume — do this first**

Storage is local SQLite, not a hosted database. Railway's container filesystem
is **ephemeral**: without a volume, a redeploy deletes every submission.

In the Railway service: Settings → Volumes → New Volume, mount path `/data`.
Then set `DB_PATH=/data/bot.db`. The schema creates itself on first boot.

Attach the volume **before** you go live. If you collect 2,000 submissions and
then attach a volume, that data is already gone.

**2. BotFather**

Create the bot, copy the token. Add the bot as an **admin** of the channel or
group where the report gets published, with permission to post and edit
messages. Without edit permission the live report cannot refresh.

**3. Railway**

Deploy from this repo. Add the variables from `.env.example`. Set the service
type to **Worker**, not Web — this bot uses polling and does not listen on a
port.

To find your own Telegram ID for `ADMIN_IDS`, message `@userinfobot`.
For `REPORT_CHAT_ID`, forward any message from the target group to
`@userinfobot`; the ID starts with `-100`.

**4. Verify**

On boot the bot DMs every admin with the database path and the row count. If
that message says `/data/bot.db` and the logs carry no volume warning, storage
is wired correctly. Then send `/admin` → Dashboard.

---

## How it behaves

**Before 4 PM IST** — registration only. Name, roll number, date, shift,
category, then centre as an optional extra step after saving. The Submit
button is visible but locked.

**At 4 PM IST** — the window opens automatically and everyone registered gets
a notification, drained gradually through the broadcast queue. If the official
key slips, Admin → Open Submission Now does it manually.

**After submitting** — the candidate sees their total, their percentile inside
their own shift, the shift median, their category median, and the band.
Followed by a share button and a course suggestion that branches on whether
they landed inside the band.

---

## Design decisions worth knowing

**Local SQLite, not a hosted database.** Every query is a disk read instead of
a network round trip, which is what keeps the 4 PM rush fast. WAL mode is on
so reads never block the writer. The cost is that backups are your job, which
is what the backup system below is for.

**Conversation state is in the DB, not memory.** A Railway redeploy at 4:30 PM
does not wipe half-finished submissions. Every step reads and writes
`sessions`.

**Submission unlocks on a date and time, not a time of day.** A time alone
would open the window at 4 PM on whatever day the bot happened to be running,
including days before the answer key is out. With `SUBMISSION_OPEN_DATE`
unset the bot stays closed until an admin opens it.

**Roll number is the unique key.** One person with three Telegram accounts
cannot submit three times.

**Marks are validated arithmetically.** With 0.25 negative marking,
`marks = 1.25 × correct − 0.25 × attempted`, so only a fixed set of scores is
possible for any attempt count. 48 with 50 attempted is rejected at entry with
the nearest valid scores suggested. Verified against all 1,326 GK
combinations.

**Medians are trimmed, not averaged.** Top and bottom 5% of each shift are
dropped, so a few joke entries cannot move a difficulty label.

**Difficulty labels freeze at 50 entries per shift.** A public post that flips
Hard → Moderate → Hard loses the audience's trust.

**No normalised score is ever shown.** Real normalisation needs the full
candidate population. Percentile-within-shift is the honest version, and every
output carries the disclaimer.

**Report edits are hashed and throttled.** Identical content is skipped
(Telegram rejects unchanged edits), refresh runs every 5 minutes, and
`RetryAfter` is handled rather than crashing the job.

---

## Admin panel

`/admin` or the menu button.

| Feature | What it does |
|---|---|
| Dashboard | Registered, submitted, last 24h, queue depth, key coverage |
| Shift Difficulty | Per-shift n, median, high, avg attempted, label, lock status |
| Category Bands | Per-category n, median, band |
| Answer Key Coverage | Which of the 24 slots are in |
| Outlier Queue | Entries 20+ marks above their shift median |
| PDF Report | Branded PDF, the WhatsApp-shareable version |
| CSV Export | Full submission dump |
| Publish / Update | Preview → publish → auto-refresh every 5 min |
| Open Submission Now | Manual unlock override |
| Backup Now | Consistent snapshot, delivered as a Telegram file |
| Restore | Upload a backup, review counts, type RESTORE to confirm |

Commands: `/flag <id>`, `/unflag <id>`, `/broadcast`, `/deletemydata`.

---

## Backup and restore

Snapshots use SQLite's own backup API, so they are consistent even while the
bot is writing. A plain file copy can catch a half-written transaction.

Automatic backups run every `BACKUP_INTERVAL_HOURS` and on shutdown, delivered
to `BACKUP_CHAT_ID` as a Telegram document — offsite, free and permanent.
`Backup Now` sends one on demand.

Restore is deliberately slow: upload the `.db`, the bot validates the schema
and shows row counts for both the backup and what is currently live, then you
type `RESTORE` in full to go ahead. The database being replaced is kept on the
volume as `bot.db.replaced_<timestamp>`.

---

## Launch-day checklist

1. Confirm the volume is mounted — the boot DM shows the path and row count,
   and the logs shout if `/data` is missing.
2. Set `SUBMISSION_OPEN_DATE` to the day the answer key drops.
3. Confirm the paper pattern in `config.py` matches the actual 2026 paper.
   **The 23 May 2026 corrigendum changed the Mode of Selection table — if the
   real split is not 50 + 20, change `GK_QUESTIONS` / `EN_QUESTIONS` before
   going live.** Everything else derives from those two numbers.
4. Post the announcement, open registration.
5. Watch Dashboard as registrations come in. Hit Backup Now once before 4 PM.
6. At 4 PM confirm the window opened and the queue is draining.
7. Around 100 submissions you get a nudge. Preview, then publish.
8. Export the PDF once the numbers settle and push it to WhatsApp groups.

---

## Not built yet

- **Post-result loop** — pinging submitters with "did you qualify?" to capture
  the real cutoff. The `qualified` column exists in the schema, ready for it.
- **Answer key files are stored as Telegram file_ids, not copied to disk.**
  Simpler, and it keeps the database small enough to send as a backup. The
  `storage_path` column is there if you later want them mirrored.
- **Referral unlock is counted but the reward is the text breakdown.** If you
  want it to unlock the PDF instead, that is a small change in
  `handlers/stats.py`.
