# 9. Demo Script (10 minutes, in class)

A step-by-step version in Hebrew, with troubleshooting, is in [`מדריך.md`](../מדריך.md).

## Rehearse alone first (the day before)
1. `python3 run.py --pin 2468`, open the printed lecturer address, log in, start a class.
2. In a second terminal: `python3 tools/simulate_class.py --pin 2468 --students 30`.
   The dashboard fills with 30 students, a poll runs, questions and homework arrive.
3. Walk through the timeline below with your own phone as the one real student.
4. Delete `classica.db` afterwards, so the real demo starts clean.

## Before class (5 min of setup)
1. Connect the laptop to the projector. Turn on a **phone hotspot** and connect the laptop to it, in case the campus Wi-Fi blocks devices from reaching each other.
2. Optional, for the real LLM: `export ANTHROPIC_API_KEY=...`
3. Run `python3 run.py --pin 2468`. Open the printed **lecturer** address (`http://localhost:8000/lecturer`) and log in.
4. Check with your own phone that the "Students reach it" address opens. If it doesn't, fix the network now, not during the demo.
5. Keep `demo/sample-lecture.vtt` and `demo/homework-samples.md` open.

## Timeline
| Time | What to show | Feature |
|---|---|---|
| 0:00–1:00 | The problem: attendance, polls and feedback are split across many tools, and nothing is LLM-ready. Show the architecture diagram (`docs/05-components.md`). | Context |
| 1:00–4:00 | Click **Start**, then **Full screen** on the QR. **The whole class scans.** The counter climbs live. Point out that the QR and the code change every 20 s, so a photo sent home is useless. Try to check in a second student from your own phone to show the rejection. Add one student by hand. Click **Excel** and open the file: three sheets. | 1 (main) |
| 3:30–4:00 | **Head count:** take a photo of the class from the front in the "Head count" card. Boxes appear on the people; compare "Checked in" with "In the photo". Say that the photo never leaves the laptop and nobody is identified. | 1 (main) |
| 4:00–5:30 | Click the **Understood?** template and launch it. The class votes and the bars move live. Close the poll. | 3 |
| 5:30–6:30 | Ask the class to send a question in the Questions tab and upvote. Mark one as answered, hide one. Show one phone in airplane mode that sends once it's back online. | 2 |
| 6:30–8:00 | Upload `sample-lecture.vtt`, click **Summarise**, then **Share with students**: a Summary tab appears on their phones. Explain the strategy pattern: the LLM if available, otherwise the offline summary. | 4 |
| 8:00–9:30 | Three volunteers paste answers A, B and C from `homework-samples.md`. Show one student's review, then the lecturer view where A↔C is flagged. | 5 |
| 9:30–10:00 | Wrap up: 97 tests, zero installs, Hebrew and English, 200 simulated phones, the design documents. Q&A. | n/a |

Optional, if someone asks about cheating: switch the language to Hebrew, and explain the location check
(what it can and can't do is in the tools report, 1.3). Only demo it live if you set up an HTTPS tunnel and tried it beforehand.

## Fallbacks
- **Phones can't reach the laptop:** use the hotspot. Or run a tunnel (for example `cloudflared tunnel --url http://localhost:8000`) and restart with `--public-url <tunnel address>`.
- **A student's camera won't scan:** they open the address written under the QR and type the 6-digit code.
- **A phone is dead:** add the student by hand in the attendance card.
- **No internet for the LLM:** the offline mode works automatically. Mention it as a designed feature.
- **You restarted the server:** the dashboard returns to the login screen; log in again. Students who already checked in stay checked in.
