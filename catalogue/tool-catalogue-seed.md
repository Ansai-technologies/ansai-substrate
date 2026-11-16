# TOOL CATALOGUE — SEED LIST (25 Oct 2026)
Source material: the "50 websites" poster he shared + his own notebook page (REA circled at top).
Sorting rule: an entry earns a place by AGENT VALUE — would an agent call this mid-task?
Routes: API-WRAP (site has an API → thin MCP server) · REBUILD (the function is simple → our own native MCP tool, no dependence on the site) · RESOURCE (content exposed as MCP resources/search) · CATALOGUE-ONLY (human value, low agent value) · SKIP (never carried).

## API-WRAP (wrap their API as an MCP server)
- WolframAlpha — compute/answer engine (API)
- VirusTotal — file/URL malware scanning (API)
- HaveIBeenPwned — breach exposure check (API)
- Semantic Scholar — academic paper search (API)
- Archive.org — web archive + media library (API) [also RESOURCE]
- remove.bg — image background removal (API)
- TinEye — reverse image search (API)
- Raindrop.io — bookmark manager (API)
- Cleanup.pictures / Unscreen — object & video-background removal (API/partner)
- Gutendex for Project Gutenberg — 70k public-domain books (API) [also RESOURCE]
- AlternativeTo — software alternatives data (partial API)
- JustWatch — where content streams (partial/unofficial API)
- DownDetector — outage status (partial)

## REBUILD (recreate the function as our own tool)
- regex101 → regex test + explain
- JSONFormatter → JSON validate/format/pretty
- CodeBeautify → code formatter (libraries)
- ExplainShell → shell command explainer
- Squoosh → image compression (sharp)
- Smallpdf / iLovePDF → PDF merge/split/compress (pdf-lib)
- Carbon.now.sh / Ray.so / Shots.so → code & product image rendering (headless render)
- SmartMockups → device mockup compositing
- Summarize.tech → YouTube transcript + summary

## RESOURCE (content libraries, search + read)
- Project Gutenberg · Archive.org · OpenCulture

## CATALOGUE-ONLY (human-delight; not agent tools)
- Radio Garden · EveryNoise · TuneFind · MusicForProgramming · MyNoise · Coffitivity
- Photopea (too large to rebuild; browser-only) · Phind · Elicit · Consensus · SciSpace · Connected Papers (research assistants — revisit if APIs open)
- SimilarSites · Fast.com · File.io · Privnote

## SKIP (never carried — piracy, paywall circumvention, abuse vectors)
- 12ft.io (paywall bypass) · LibGen · Sci-Hub · PDFDrive (piracy)
- Temp-mail.org · 10MinuteMail (disposable mail — abuse-prone)

## FROM HIS NOTEBOOK (his own transcription, 25 Oct — supersedes my readings)
Header: "Google dorking" · REA (circled)
Left: TinyWow (x2) · Messenger.abeto.co · Best AI AI · GetArt.ai · Morphic · Rundble · Osiris · Axiom · Wolfram Alpha · Open source alt · Zpencil app · demo.famaip.com · Clip Goat · Home by MC · Abacus AI · Printful.com · InfinityFree · Angerity
Right: Logo Diffusion · Arena · Human/biodigital · SEOStudio.tools · Gods Eye View · Exercism · Ninite · Learn Anything · Bloxlizer · Watabou.github.io · Imagine, explained · With Diode · Desktopphut · Fck Signups · Mods Nation · Learn Kata · Story Tribe

Identification notes (mine, for sorting): TinyWow = a bundle of free mini-tools (PDF/image/writing) — a mini-catalogue in itself, REBUILD/API candidates throughout. Printful = print-on-demand WITH a public API (API-wrap candidate). Axiom — if axiom.ai, browser automation (agent-adjacent). Morphic — AI search/site builder. Arena — model arena. Exercism — coding practice (content). Ninite — bulk app installer (Windows ops utility). Watabou — procedural map/dungeon generators. SEOStudio.tools — SEO mini-tools bundle (REBUILD candidates). Logo Diffusion / GetArt.ai — AI image tools.

## VERIFICATION PASS (25 Oct)
Live-tested keyless + docs-checked for every API-WRAP candidate; full machine-readable registry: catalogue.v1.json.
- WolframAlpha — api-wrap: real API, free AppID key required (2,000 free non-commercial calls/mo); keyless test returned "Appid Missing".
- VirusTotal — api-wrap: real API, free key required (4 req/min, 500/day, non-commercial only); keyless test 401.
- HaveIBeenPwned — api-wrap: split door — Pwned Passwords is FREE and keyless (live test 200) while email breach lookup needs a paid key (from $5.29/mo; keyless test 401). Wrap the free half now.
- Semantic Scholar — api-wrap: free, keyless works but is throttled (live test HTTP 429, as before); a free API key (1 req/sec) makes it dependable.
- Archive.org — api-wrap: FULLY OPEN, no key at all (live tests 200 with real data). The reference case.
- remove.bg — api-wrap: real API, free key required (first 50 calls/mo free at preview size); keyless test 403 auth_failed.
- TinEye — api-wrap (parked): real API, paid key only, bundles from $200/5,000 searches, no free tier; keyless test 401.
- Raindrop.io — api-wrap: real API, free, needs the founder's OAuth/test token; keyless test 401.
- Cleanup.pictures — api-wrap via its sibling: cleanup.pictures itself has NO API; the Clipdrop API's cleanup endpoint does the same job (key required; keyless test 401).
- Unscreen — api-wrap (parked): API exists under paid Unscreen Pro plans only, no free tier; keyless test reached the host but no data without a key.
- Printful — api-wrap: API free (pay only for fulfilled products); v1 catalogue is publicly readable (live test 200 keyless), v2/orders need OAuth (test 401).
- Project Gutenberg (Gutendex) — resource: free and keyless (live test 200, real book data); expose as search-and-read resources, not a tool.
- AlternativeTo — drop: no official public API exists (alternativeto.net/api/ returns 404).
- JustWatch — drop: API is partner-only by manual application; the unofficial endpoint bans commercial use.
- DownDetector — downgrade-to-rebuild: official API is Enterprise-subscription only (OAuth, custom pricing, no free tier); the "is it down?" job is simple enough to build ourselves.
