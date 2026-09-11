# Demo v2: streaming conversation, avatar and guided review

Agreed with the operator on **11 September 2026**.
Target: an improved, presenter-led demonstration during the week beginning
14 September 2026. The exact presentation date is not specified.

## Outcome and approved tradeoff

Deliver a more natural German voice conversation with a real Foundry Voice Live
avatar, clear microphone controls, visible sources and a reliable spoken or
button-driven handoff to a reviewed Word summary in SharePoint.

The operator explicitly approved **streaming demo mode**: play conversational
audio/video as it is generated instead of waiting for the entire answer and a
separate evidence-model round trip. This removes the independent **pre-speech**
evidence check in that mode. Source restrictions, grounding instructions, source
references, unsupported-question handling and service safety controls remain.
They are not equivalent to independently validating every spoken statement.

Keep the current **strict mode** available. Streaming must be explicitly configured
and visibly labelled; do not silently change the assurance level. A later check
cannot retract something the user already heard. Do not label streaming answers
as independently verified.

Both modes retain stronger validation for the final written summary, human
review/editing, explicit version-bound save approval, and real upload confirmation.
The existing source-ID validation alone is not a semantic summary-grounding check;
implement and test the additional final-output validation rather than claiming it
already exists.

## Current baseline and evidence

- One versioned Foundry **prompt agent**, not a hosted or multi-agent system.
- GPT-5.1 `2025-11-13`, **Standard** deployment in Sweden Central; the former
  GlobalStandard deployment was retired. Keep this model and geography initially.
- Local FastAPI backend and browser UI; SharePoint input/output use the explicitly
  approved application identity with existing `Sites.Selected` grants.
- Six synthetic SharePoint PDFs, 12 pages, are loaded as a bounded snapshot at
  session start. Source references and versions are preserved; repository PDFs
  are not runtime grounding.
- A real-service journey passed using a synthetic browser microphone: cited
  answer, typed contextual follow-up, changed position, summary edit/apply,
  approved Word upload/download and duplicate-free retry.
- Human rehearsal exposed slow replies and interruption issues. Subsequent fixes
  include semantic VAD, noise suppression, stale-interrupt handling and correlated
  cleanup errors; noisy-room acceptance remains open.
- Corpus load improved from 16.27s to 4.84s in one comparison. A browser run
  started its session in 6.33s, but validated conversational turns still took
  roughly 5-15s. A direct probe produced first upstream audio in 1.29s; that was
  not first audible playback because strict mode buffered it.
- Spoken summary commands already include **"OK, jetzt Zusammenfassung erstellen"**
  and **"Bitte meine Meinungsbildung zusammenfassen"**. They publish a draft event
  for the review UI. Verify and improve this complete handoff; do not treat
  requesting a summary as permission to save it.
- Avatar-ready UI improvements were implemented locally during reference research.
  Avatar transport is not implemented or enabled yet. Existing uncommitted work
  must be preserved and reviewed, not assumed deployed or included in the
  plan-only commit.

## Reference implementation and reuse boundaries

Reference: [Azure-Samples/voicelive-api-salescoach](https://github.com/Azure-Samples/voicelive-api-salescoach),
inspected at commit `38568ddf3fc040b6f6d0d2bc4b3829a31ec06966`.
The checkout is isolated under ignored `.local/reference/`.

Useful implementation references:

- `frontend/src/hooks/useWebRTC.ts`: peer connection lifecycle, receive-only media
  tracks, ICE gathering, SDP exchange and connection cleanup.
- `frontend/src/app/App.tsx`: ICE configuration from service session events and
  `session.avatar.connect` signaling.
- `backend/src/services/websocket_handler.py`: avatar/session configuration and
  bidirectional Voice Live event forwarding.
- `backend/src/services/managers.py`: scenario instructions loaded before a
  conversation and short-response guidance. Its agent path uses `tools=[]`.
- `backend/src/app.py` and `graph_scenario_generator.py`: the optional Graph
  scenario is built before conversation from canned calendar JSON; this is not
  a live SharePoint RAG implementation.

Reuse patterns selectively, not the whole architecture. Preserve the sample's
MIT notices if adapting its code. Do not copy its arbitrary event forwarding,
raw logging/recording, unrelated role-play behavior or default model/deployment
choices. No React/Fluent migration, new hosted agent, search service or database
is required just to add an avatar.

Official references to recheck while implementing:

- [Voice Live with Foundry agents](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-agents-quickstart)
- [Voice Live session and avatar configuration](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-how-to)
- [Real-time avatars and network prerequisites](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech-avatar/real-time-synthesis-avatar)
- [Speech service regions](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions)
- [Model performance and latency](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/latency)

## Implementation work

### 1. Explicit delivery modes and latency

- Add a validated configuration choice: `strict` versus `streaming`.
- Keep `strict` as the safe code/template default. Explicitly enable `streaming`
  for this approved synthetic demo and show its limitation in the UI.
- In streaming mode, release incremental audio/text without the blocking
  independent evidence-model call. Preserve a complete, ordered conversation
  and distinguish cancelled/partial output from a completed answer.
- Prefer short spoken responses: usually 1-3 sentences and at most one focused
  follow-up question. Offer more detail when requested; do not mechanically
  truncate facts or remove important caveats.
- Keep GPT-5.1 Standard initially so the effect of streaming can be measured
  independently from a model switch.
- Keep the full six-document snapshot initially. Do not move untrusted document
  content into trusted system instructions or replace it with an unverified
  lossy summary.
- Consider smaller model benchmarks, a source-linked compact briefing, or
  targeted retrieval only after measurements identify a remaining bottleneck.
  Any model replacement must meet the approved Standard/EU Data Zone constraint.
- Measure end-of-user-speech, first received audio, first actual playback, answer
  completion and interruptions separately. Target roughly **2-3s to first audible
  reply** for ordinary questions, with median and slower-case results reported.
  This is an engineering target, not a guarantee.

### 2. Native Foundry Voice Live avatar

- Implement a stock avatar using native Voice Live avatar configuration and
  WebRTC signaling/media, aligned with the selected prompt agent and conversation.
- Start with one supported stock character/style. No custom training or personal
  likeness upload is in scope.
- Validate current regional/API support and network requirements, including TURN,
  using the existing approved resource before adding infrastructure.
- Keep Entra/service credentials server-side. Only the necessary ephemeral ICE
  credentials and SDP may reach the local browser; never log or persist them.
- Restrict forwarded signaling to expected event shapes, sizes and lifecycle
  states. Do not turn the backend into an arbitrary Voice Live event proxy.
- Native avatar media is supported initially in **streaming mode**. Strict mode
  remains audio-only unless a separately tested synchronized, evidence-gated
  media path is implemented. Muting live avatar video and later playing delayed
  PCM is not an acceptable synchronization strategy.
- Avoid double audio: when avatar audio is active, do not also play PCM deltas.
  Connect the avatar before starting its first answer, or expose a clear
  audio-only fallback; never imply a ready avatar while negotiation is incomplete.
- Handle interruption, mute, disconnection, timeouts and cleanup. Release peer
  connections, media elements and billable sessions on Stop/session deletion.
- Keep a working **audio-only** choice. If avatar setup fails, explicitly offer
  fallback rather than silently replaying a partial response or misreporting
  success.
- No automatic switch to global model processing or relaxed network policies.
  Model region alone is not an end-to-end EU Data Boundary certification.

### 3. Voice-first UI and experience

Problems to address:

- Conversation, connection state and review currently compete for attention.
- Listening, processing and speaking need distinct, truthful visual states.
- Transcript/source detail should not crowd the primary voice/avatar stage.
- The transition from conversation to draft review needs clearer guidance.

Planned experience:

- Prominent conversation stage with avatar or honest audio-mode placeholder.
- Nearby microphone on/mute, interrupt, playback mute and finish controls.
- Explicit pre-session avatar choice, connection progress, retry and fallback.
- Secondary accessible transcript/source panels, with real source links.
- Clear review steps: **draft -> edit/apply -> approve/save -> saved link**.
- A spoken summary request opens/focuses the review UI just like the button;
  routine updates must not steal keyboard focus.
- Preserve keyboard support, accessible names/toggle states, visible error
  recovery and mobile layouts without horizontal overflow.
- No automatic microphone capture, fabricated listening indicators, raw audio
  recording or misleading avatar-readiness state.

### 4. Voice-to-summary handoff and final output

- Exercise supported spoken phrases and add conservative variants where useful.
  Negated, quoted/discussed commands must not inadvertently finish or save.
- Ensure pending spoken/typed turns are incorporated once before summarization.
- Stop avatar/audio playback appropriately when entering review.
- Validate summary sources and factual claims against the approved corpus, and
  expressed user positions against the conversation. Preserve the latest stance
  and explicitly represent uncertainty.
- Recheck relevant content after user edits without rejecting a subjective
  position merely because it differs from document recommendations. A clearly
  subjective user opinion is not a document fact.
- If validation fails, show a recoverable failure and keep saving blocked.
  Do not silently substitute an empty summary or claim validation passed.
- Retain the exact headings:
  **Haltung zum Thema**;
  **Fragen, die noch geklärt werden müssen**;
  **Gegenpositionen**.
- Spoken saving stays explicit and bound to the presented draft version.
  Form-edited drafts require renewed approval. A generic "yes" or a summary
  request is not save authorization.
- Preserve frozen document bytes, safe retries, storage metadata-aware DOCX
  integrity checks and confirmed SharePoint links.

## Sequence and acceptance

1. **Document, commit and push this plan first.** Keep unrelated pending code out
   of that plan-only commit.
2. Finish the mode boundary and short-answer behavior; validate strict-mode
   regressions and streaming event ordering.
3. Wire avatar signaling/media and integrate the prepared UI. Keep audio-only
   behavior intact.
4. Strengthen and exercise summary validation and spoken UI handoff.
5. Run a bounded real-service test matrix, record measured latency and fix observed
   defects. Use synthetic data and clean up only explicitly owned test artifacts.
6. Rehearse with the operator's actual microphone, speakers/headset and network.
   Synthetic microphone tests are not physical hardware or noisy-room sign-off.
7. Update setup/handoff documentation and review the resulting code checkpoint
   before committing/pushing implementation changes.

Acceptance cases:

- Spoken German greeting, real avatar frames and a single synchronized audio path.
- Grounded fact, conflicting-source question, unsupported question and contextual
  typed follow-up. Streaming output is not labelled independently verified.
- Interruption while speaking and while processing; no stuck turns, late playback
  or spurious fatal cleanup errors.
- Spoken finish, changed position, review/edit/apply, rejected stale approval,
  successful Word save/download and retry without duplicate files.
- Avatar negotiation failure, audio-only fallback, mute, Stop and cleanup.
- Strict mode still withholds unchecked audio and never silently enables streaming.
- Latency results include first playback and slower cases, not only model
  first-token timing.

## Boundaries and remaining risks

- Presenter-led localhost, single-user, synthetic data only.
- Existing application SharePoint access is not per-participant permission
  trimming; input/output folder separation is not an ACL boundary.
- No new tenant-wide consent, secret rotation, sharing links or ACL changes.
- Existing reduced-scope C2/privacy limitations remain; this plan does not convert
  the demo into production compliance evidence.
- Avatar usage is billable and can fail on customer networks even when audio works.
- Streaming can speak an unsupported statement before detection. This is the
  approved demo tradeoff, not a guarantee eliminated by prompt engineering.
- Implementation and live results must be distinguished from planned work.
