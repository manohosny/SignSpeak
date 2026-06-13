# Screenshots

Drop PNGs here using the exact filenames below so the links in the root
`README.md` "Screenshots / Demo" section resolve. Capture at ~1280×800,
light theme unless noted.

| Filename | Screen to capture |
|----------|-------------------|
| `01-login.png` | Login / sign-up page |
| `02-dashboard.png` | Dashboard after login (meeting history) |
| `03-create-meeting.png` | Create-meeting dialog showing the shareable code (e.g. `XKF-8291`) |
| `04-waiting-room.png` | Waiting room before the second participant joins |
| `05-speaker-view.png` | Speaker view: live captions + transcript panel |
| `06-reader-view-avatar.png` | Reader view: 3D signing avatar mid-sign |
| `07-gloss-feed.png` | Gloss feed / pending-sign feedback panel |
| `08-direction-b-signing.png` | Reader signing at camera (Direction B) with recognized words |

## How to capture
1. Start the stack (`docker compose watch`) with mock ML modes for speed
   (`STT_MOCK_MODE=true`, `TTS_MOCK_MODE=true`, `SIGN_TO_TEXT_MOCK_MODE=true`,
   `TRANSLATION_MOCK_MODE=true` in `.env`), or point at the live demo.
2. Open two browser windows (one speaker, one reader) joined to the same code.
3. Capture each screen above. Crop to the app; avoid browser chrome where possible.
