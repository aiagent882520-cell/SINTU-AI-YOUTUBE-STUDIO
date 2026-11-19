# Ten-fort Hindi short: offline acceptance evidence

The offline acceptance topic is:

`भारत के 10 रहस्यमयी किलों पर 60 सेकंड का हिंदी वीडियो बनाओ`

The reproducible fixture covers ten forts using a curated set of official tourism, government, museum-trust and UNESCO source records. It is not a claim that the CI run performed a live web-research session. The Bhangarh supernatural story is explicitly identified as folklore rather than established fact.

## Acceptance contract

- 10 named forts and 10 source records, each with a factual claim, source type and URL
- 15 storyboard shots, each rendered for 4 seconds
- 15 timed Hindi subtitle entries burned into the output
- Hindi eSpeak NG narration, locally generated music and SINTU watermark
- 60-second target, portrait 720x1280 H.264/AAC output
- Renderer verification of final output bytes and metadata
- No public upload, paid provider or publishing action

## Image provenance

When no configured ComfyUI model host is available, the fixture uses SINTU Procedural Art (offline). This produces locally generated procedural illustrations and is not generative-AI image inference. The report records the actual provider. Real ComfyUI inference remains dependent on an externally configured model host and model assets.

## Running the acceptance

```bash
python scripts/live_e2e.py --offline-storyboard --topic "भारत के 10 रहस्यमयी किलों पर 60 सेकंड का हिंदी वीडियो बनाओ"
```

The CI job also performs the branded-video motion audit and stores its MP4 and JSON reports as a workflow artifact when dependency provisioning succeeds.
