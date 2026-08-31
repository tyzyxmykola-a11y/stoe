# Original SToE prototype (historical)

`engine.py` is preserved from the earliest top-level engine source. It applies
prompt-based operators in an interactive loop and asks the model to score
outputs. It records inputs and responses in `output_<timestamp>.txt`.

It uses `requests` and `python-dotenv`, reads `OPENROUTER_API_KEY` from the
environment / a local `.env`, and sends that key as a Bearer credential to
`https://openrouter.ai/api/v1/chat/completions`. The hard-coded model identifier
is historical; its availability has not been checked. Running this program can
send prompt content to an external provider and incur charges.

No API key, `.env`, memory file, or output log is included. Do not treat this
archived prototype as the supported entry point. It is useful for comparing
prompt-only operators with v3's graph-aware operators and structural evaluator.
