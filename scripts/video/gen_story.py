import json, os, sys, urllib.request, concurrent.futures
lines = [
 "Hey, this is Ayush, and I built RecallOps.",
 "Here's the problem I wanted to solve. Last December, the FDA found recalled baby formula still being sold in over 175 stores across 36 states.",
 "Think about that. A product was recalled, but somehow, it was still reaching customers.",
 "And this isn't just a one-time problem. We looked at nearly 2,000 FDA recalls, affecting every single state in the country.",
 "So I built RecallOps using Snowflake and Claude. Here's how it works.",
 "When a recall comes in, Claude reads the notice, identifies the affected products and lot numbers, and figures out exactly what needs attention.",
 "Then Snowflake connects those products to inventory across stores and identifies orders that could be affected.",
 "From there, a human can approve the holds, and RecallOps blocks the recalled inventory while letting safe products continue moving.",
 "Everything runs inside Snowflake, with a complete audit trail.",
 "There are over 45,000 supermarkets in America, and a single recall can create millions in losses.",
 "With RecallOps, we're making sure recalled products get caught before they reach another customer.",
]
key, voice = sys.argv[1], sys.argv[2]
def gen(i):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": lines[i], "model_id": "eleven_multilingual_v2",
                         "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35}}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            open(f"st{i+1:02d}.mp3", "wb").write(r.read()); return f"st{i+1} ok"
    except urllib.error.HTTPError as e:
        return f"st{i+1} HTTP {e.code} {e.read()[:200]}"
with concurrent.futures.ThreadPoolExecutor(6) as ex:
    for r in ex.map(gen, range(len(lines))): print(r)
