# BehaveGuard Kaggle showcase

This directory contains two publication artifacts:

- `behaveguard-dataset/` — the upload-ready, privacy-preserving Kaggle Dataset package.
- `behaveguard_showcase.ipynb` — the fully executed notebook with EDA, classical and neural training, evaluation, and 16 figures.

## Rebuild locally

```bash
uv run python scripts/export_kaggle_dataset.py
uv run python scripts/build_kaggle_notebook.py
```

The exporter reads the gitignored `Behaveguard-client.xlsx`. A local `.kaggle_export.local.json` can define a pseudonym salt and alias groups; it is deliberately excluded from git and must never be uploaded.

## Publish the dataset

Authenticate with the current Kaggle CLI, inspect the data card and custom data notice, then create the dataset privately first:

```bash
uvx kaggle auth login
uvx kaggle datasets create -p kaggle/behaveguard-dataset
```

Review the private Kaggle preview for names, literal keys, timestamps, and coordinate fields before changing its visibility. The dataset publisher is responsible for confirming participant consent and the legal basis for releasing behavioral-biometric data. Kaggle also supports `--public`, but do not use it until that review is complete.

## Publish the notebook

The simplest route is to create a Kaggle Notebook, attach the newly uploaded dataset, and import `behaveguard_showcase.ipynb`. The loader searches common Kaggle input paths automatically.

For CLI publication, initialize notebook metadata in a temporary upload folder, replace the generated owner/slug placeholders, and push it:

```bash
mkdir -p /tmp/behaveguard-kaggle-notebook
cp kaggle/behaveguard_showcase.ipynb /tmp/behaveguard-kaggle-notebook/
uvx kaggle kernels init -p /tmp/behaveguard-kaggle-notebook
uvx kaggle kernels push -p /tmp/behaveguard-kaggle-notebook
```

The notebook runs on CPU and does not require internet access. Its classical metrics use five chronological within-session folds; the neural model uses a single final-window validation split. Keep the development-only caveat visible in the Kaggle title and description.
