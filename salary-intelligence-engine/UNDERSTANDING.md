# Understanding This Project

A plain-language map of what each part does.

## The big idea

You give the system a job posting. It guesses the salary. We build several guessers, measure how wrong each one is, then combine them so the final guess is better than any single one.

Analogy: asking five friends to guess a house price, checking who is closest, then averaging the best guesses.

## Folders

| Folder | What it does | Analogy |
|--------|--------------|---------|
| `data/` | Holds the job postings and salaries (raw and cleaned). Not uploaded to GitHub. | The ingredients pantry |
| `notebooks/` | Experiments and training runs (baselines, fine-tuning on Colab/Kaggle). | The test kitchen |
| `src/` | Reusable Python code: cleaning, models, RAG, agents. | The recipe book |
| `backend/` | FastAPI server that takes a job posting and returns a salary. | The kitchen window where orders arrive |
| `frontend/` | Next.js dashboard that shows predictions and compares model errors. | The restaurant menu and dining room |

## Files

| File | What it does |
|------|--------------|
| `README.md` | Progress table, error comparison, architecture, demo link. |
| `UNDERSTANDING.md` | This file. What each area does. |
| `.gitignore` | A "do not upload" list for secrets, big data and model files. |

## Stages in one line each

1. **Data:** collect and clean job postings, split into train (learn), validation (tune), test (final exam).
2. **Baselines:** simple models that set the score to beat.
3. **Fine-tune:** teach a small language model (Llama 3.2 3B) to guess salaries.
4. **RAG pricer:** look up similar jobs, then ask a free LLM to estimate from them.
5. **Ensemble:** blend all guesses with Linear Regression.
6. **Agents:** Scanner finds postings, Planner decides, Messenger sends a phone alert.
7. **Backend + Frontend:** serve it all through an API and a dashboard.
8. **README:** show the final results table and live demo.

## Key words

- **Error (MAE):** on average, how many dollars the guess is off. Lower is better.
- **Train / validation / test:** study material, practice quiz, final exam.
- **Embedding:** turning text into numbers so similar jobs sit close together.
- **QLoRA:** a cheap way to fine-tune a big model by training only a small add-on.
