# EU-CFA Network tracker

Network, overlap and events views of European public financial institutions in the CFA franc zone
(WAEMU and CEMAC), built from the data of the EU-CFA Public finance tracker.

- `network.py` builds the site (no extra software needed).
- `data/tracker.json` is the tracker's data (refreshed automatically once `TRACKER_DATA_URL` is set in `network.py`).
- `data/events.csv` is the event log: one row per event, with a source link. Edit it on GitHub to add events.
- The site rebuilds on the 1st of each month and whenever a file changes.

Events columns: date (YYYY-MM-DD), end_date, status (past / upcoming / to be confirmed), category
(Monetary, Politics & security, EU–Africa policy, Financing instrument, Summit / meeting), countries
(ISO codes separated by |, or ALL), title, description, source_url.
