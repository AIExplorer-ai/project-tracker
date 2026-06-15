# Project Tracker

A personal project tracking system with SQLite database and AI-powered summaries via Claude.

## Setup (one time)

```bash
# 1. Install Python 3.8+ if not already installed

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python project_tracker.py
```

Then open http://localhost:5000 in your browser.

## Your data

All project data is saved in `projects.db` (SQLite) in the same folder.
This file is your database — back it up like any important file.

## AI Summary

1. Click "AI Summary" in the sidebar
2. Enter your Anthropic API key (get one at https://console.anthropic.com)
3. Choose period: This month / This quarter / All time
4. Click "Generate summary"

Past summaries are saved in the database and viewable anytime.

## File structure

```
project-tracker/
├── project_tracker.py ← Flask server + API
├── requirements.txt  ← Python dependencies
├── projects.db       ← Your data (auto-created)
├── README.md
└── static/
    └── index.html    ← The UI
```
