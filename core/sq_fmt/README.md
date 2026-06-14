# sciqnt-fmt

Pure formatting substrate for sciqnt — number/percentage formatters, ANSI colour
tokens, key:value + table renderers, and braille terminal charts. **Zero
dependencies** (stdlib only).

This is the thin leaf that connectors and other units depend on to render money
the same way everywhere *without* pulling in prompt-toolkit. The interactive
layer (`sciqnt-tui`) builds on top of this and re-exports these names for
backward compatibility. The dependency arrow only ever points one way:
`sq_tui → sq_fmt`, never back.
