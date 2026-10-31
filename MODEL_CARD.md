# Chameleon layout picker (3 KB)

Hugging Face: https://huggingface.co/ppatel16/chameleon-picker

The only learned part of the Chameleon Engine: a ridge regression (78 weights + per-shape size targets, `regressor.json`,
about 3 KB, CPU/NumPy) that ranks the candidate layouts the engine generates by how close each is likely to be to a
designer's layout. Trained on 178 designer reference layouts (`data/refs/`); retrain with
`python -m tools.learn_regress --save`. Use: keep it in `engine/`, or `CHAMELEON_WEIGHTS=/path/regressor.json`.
Without it the engine falls back to a hand-set score, so the model is fully swappable.
