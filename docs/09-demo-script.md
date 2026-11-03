# 9. Demo Script (10 minutes, in class)

## Before class (5 min of setup)
1. Connect the laptop to the projector. Turn on a **phone hotspot** and connect the laptop to it, in case the campus Wi-Fi blocks devices from reaching each other.
2. Optional, for the real LLM: `export ANTHROPIC_API_KEY=...`
3. Run `python3 run.py --pin 2468`. Open the printed **Lecturer dashboard** URL and log in.
4. Keep `demo/sample-lecture.vtt` and `demo/homework-samples.md` open.

## Timeline
| Time | What to show | Feature |
|---|---|---|
| 0:00–1:00 | The problem: attendance, polls and feedback are split across many tools, and nothing is LLM-ready. Show the architecture diagram (`docs/05-components.md`). | Context |
| 1:00–4:00 | Click **Start class**, then **Full screen** on the QR. **The whole class scans.** The counter climbs live. Point out that the QR changes every 20 s, so a photo sent home is useless. Try a second check-in from your own phone to show the rejection. Click **Download spreadsheet** and open it in Excel. | 1 (main) |
| 4:00–5:30 | Click the **Understood?** template and launch it. The class votes and the bars move live. Close the poll. | 3 |
| 5:30–6:30 | Ask the class to send a question in the Comments tab and upvote. Show one phone in airplane mode that sends once it's back online. | 2 |
| 6:30–8:00 | Upload `sample-lecture.vtt` and click **Summarise**. Explain the strategy pattern: the LLM if available, otherwise the offline summary. | 4 |
| 8:00–9:30 | Three volunteers paste answers A, B and C from `homework-samples.md`. Show one student's review, then the lecturer view where A↔C is flagged. | 5 |
| 9:30–10:00 | Wrap up: 48 tests, zero installs, the design documents. Q&A. | n/a |

## Fallbacks
- **Phones can't reach the laptop:** use the hotspot, or run `cloudflared tunnel --url http://localhost:8000` and restart with `--public-url <tunnel URL>`.
- **No internet for the LLM:** the offline mode works automatically. Mention it as a designed feature.
- **The projector is too dim to scan:** the URL is printed under the QR, so students can type it.
