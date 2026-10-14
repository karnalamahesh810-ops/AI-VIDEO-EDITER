"""
Style Match (2026-10-14): paste or upload ANY video whose editing style you want; the worker measures that
style and the pipeline makes the user's video in it.

    measure.analyse(video)      -> measurements    (ffmpeg + OpenCV + local faces/text, a few cheap vision calls)
    kit.build(measurements)     -> Style Kit JSON  (brand tokens, element templates, pacing, audio, structure)
    kit.card(style_kit)         -> human-readable card (markdown)
    compare.sheet(...)          -> reference-vs-ours stills per element, with the kit's confidence
    apply.apply(doc, style_kit) -> the timeline drawn in that style (smart-spec graphics on their triggers,
                                   captions, transitions, camera, grade, audio mix)

The worker entry is run.run() (handler action "style_match").
"""
